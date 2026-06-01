#!/usr/bin/env python3
"""
导出链接清单 —— 从素材库里把每篇推文的原文链接抽出来，按时间归档 + 切成 10 个一批喂 ima

读法：扫描 素材库/<公众号>/*.md 的 frontmatter（公众号 / 标题 / 链接 / 发布时间），
不依赖正文，纯抽链接。每次全量重建（幂等、无重复），产出三份：

  素材库/链接清单.md        —— 人看：按「公众号 → 日期」分组，时间倒序（新在上）
  素材库/链接清单.csv       —— 机器用：公众号, 发布时间, 标题, 链接
  素材库/链接清单-待导入.txt —— 喂 ima：只列「还没导进 ima」的链接，按每 10 个一批，
                              每行一个纯链接，复制一整批粘进 ima 客户端即可。

为什么要「待导入」+ 已推送追踪：ima.copilot PC 客户端没有开放 API，只能手动粘链接、
且一次最多 10 个。所以这边把待办链接切成 10 个一批，并用 state/ima_pushed.json
记下「已经粘进 ima 的链接」，下次就只列新的，不用重复粘老的。

日常用法（PC 客户端手动导入流程）：
    1) 每天采集完，打开 素材库/链接清单-待导入.txt
    2) 按「第 N 批」复制 10 行链接，粘进 ima 客户端的「导入链接」框，提交
    3) 全部批次导完后，跑下面任一条标记为已推送：
         python3 export_links.py --done          # 标记当前所有待导入为已推送
         python3 export_links.py --done 3         # 只标记前 3 批（30 条）为已推送
       标记后重生成清单，待导入就清空/只剩没标的，明天只显示新链接。

其它用法：
    python3 export_links.py                       # 仅重建清单（不改已推送状态）
    python3 export_links.py -d 素材库              # 指定素材库目录
collect.py 跑完会自动调用 export()（不自动标记已推送，标记永远由你手动确认）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.yaml"
STATE_DIR = ROOT / "state"
PUSHED_FILE = STATE_DIR / "ima_pushed.json"       # 已粘进 ima 的链接集合
PENDING_FILE = STATE_DIR / "ima_pending.json"     # 上次生成的待导入快照（供 --done 按批标记）
BATCH = 10                                         # ima 一次最多导 10 个


def _parse_front_matter(text: str) -> dict:
    """抽取 md 顶部 --- ... --- 之间的 key: value。只取链接相关字段，简单稳。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields


def _collect(out_dir: Path) -> list[dict]:
    """遍历 素材库/<公众号>/*.md，返回 [{account,title,link,published,date}]。"""
    rows: list[dict] = []
    for md in out_dir.glob("*/*.md"):
        try:
            fm = _parse_front_matter(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        link = fm.get("链接", "")
        if not link:
            continue
        published = fm.get("发布时间", "")
        rows.append({
            "account": fm.get("公众号", md.parent.name),
            "title": fm.get("标题", md.stem),
            "link": link,
            "published": published,
            "date": (published or "")[:10] or "未知日期",
        })
    return rows


def _load_filter() -> dict | None:
    """读 config.yaml 的 filter 段。未启用/读不到返回 None（=不过滤，全当营销）。"""
    try:
        import yaml
        cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    fc = cfg.get("filter") or {}
    if not fc.get("enabled"):
        return None
    return {
        "blacklist": [b for b in (fc.get("blacklist") or []) if b],
        "whitelist": [w for w in (fc.get("whitelist") or []) if w],
    }


def _classify(title: str, flt: dict | None) -> str:
    """返回 '营销' / '非营销'。黑名单命中=非营销，但白名单命中可豁免（营销优先）。"""
    if not flt:
        return "营销"
    t = title or ""
    hit_bl = any(b in t for b in flt["blacklist"])
    hit_wl = any(w in t for w in flt["whitelist"])
    return "非营销" if (hit_bl and not hit_wl) else "营销"


def _load_pushed() -> set[str]:
    if PUSHED_FILE.exists():
        try:
            return set(json.loads(PUSHED_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def _write_markdown(rows: list[dict], path: Path) -> None:
    # 公众号 -> 日期 -> [行]，各层时间倒序（未知日期沉底）
    by_acct: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by_acct.setdefault(r["account"], {}).setdefault(r["date"], []).append(r)

    def date_key(d: str) -> str:
        return "0000-00-00" if d == "未知日期" else d

    filtered = sum(1 for r in rows if r.get("category") == "非营销")
    lines = ["# 推文链接清单", "",
             f"> 自动生成，共 {len(rows)} 条（其中 🚫 非营销 {filtered} 条不进 ima 待导入）。"
             f"按「公众号 → 日期」分组，时间倒序。", ""]
    for acct in sorted(by_acct):
        days = by_acct[acct]
        lines.append(f"## {acct}（{sum(len(v) for v in days.values())} 条）")
        lines.append("")
        for day in sorted(days, key=date_key, reverse=True):
            items = sorted(days[day], key=lambda r: r["published"], reverse=True)
            lines.append(f"### {day}")
            lines.append("")
            for r in items:
                mark = "🚫 " if r.get("category") == "非营销" else ""
                lines.append(f"- {mark}[{r['title']}]({r['link']})")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(rows: list[dict], path: Path) -> None:
    ordered = sorted(rows, key=lambda r: r["published"], reverse=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["公众号", "发布时间", "标题", "类别", "链接"])
        for r in ordered:
            w.writerow([r["account"], r["published"], r["title"],
                        r.get("category", "营销"), r["link"]])


def _write_pending(rows: list[dict], path: Path) -> list[dict]:
    """写「待导入」txt：只列未推送链接，**按公众号分区**、每号单独每 10 个一批
    （一批绝不跨号），各号内时间倒序。返回待导入行（快照，文件同序）。"""
    pushed = _load_pushed()
    ordered = sorted(rows, key=lambda r: r["published"], reverse=True)
    # 只把"营销活动"列入待导入；非营销噪音不喂 ima（仍在素材库/清单里、标 🚫）
    pending = [r for r in ordered
               if r["link"] not in pushed and r.get("category") != "非营销"]

    # 按公众号分组（保持各组内的时间倒序）
    by_acct: dict[str, list[dict]] = {}
    for r in pending:
        by_acct.setdefault(r["account"], []).append(r)

    total = len(pending)
    total_batches = sum((len(v) + BATCH - 1) // BATCH for v in by_acct.values())

    if total == 0:
        path.write_text(
            "# 待导入 ima 的链接\n\n（暂无新链接，全部已推送 ✅）\n", encoding="utf-8")
        _save_json(PENDING_FILE, [])
        return pending

    lines = [
        "# 待导入 ima 的链接（PC 客户端「导入链接」框，一次最多 10 条）",
        f"# 共 {total} 条 / {total_batches} 批，**按公众号分开、勿混**。逐批复制链接行粘进 ima。",
        "# 导完后标记已推送： python3 export_links.py --done           （全部）",
        "#               或： python3 export_links.py --done 示例公众号  （只标这个号）",
        "",
    ]
    snapshot: list[dict] = []                    # 每元素=一批 {account, links}
    for acct in sorted(by_acct):                 # 与 链接清单.md 同序，稳定
        items = by_acct[acct]
        nb = (len(items) + BATCH - 1) // BATCH
        lines.append(f"########## {acct}（{len(items)} 条 / {nb} 批）##########")
        lines.append("")
        for i in range(nb):
            chunk = items[i * BATCH:(i + 1) * BATCH]
            lines.append(f"===== [{acct}] 第 {i + 1} 批 / 共 {nb} 批（{len(chunk)} 条）"
                         f"——复制下面 {len(chunk)} 行 =====")
            lines.extend(r["link"] for r in chunk)
            snapshot.append({"account": acct, "links": [r["link"] for r in chunk]})
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")

    # 快照：与文件批次同序、按批存（含所属号），供 --done 按号/按批精确标记
    _save_json(PENDING_FILE, snapshot)
    return pending


def export(out_dir: Path | str = None) -> dict:
    """重建清单（md + csv + 待导入 txt）。返回 {total, pending, filtered}。供 collect.py 调用。"""
    out_dir = Path(out_dir) if out_dir else (ROOT / "素材库")
    out_dir = out_dir.resolve()
    rows = _collect(out_dir)
    flt = _load_filter()
    for r in rows:
        r["category"] = _classify(r["title"], flt)
    _write_markdown(rows, out_dir / "链接清单.md")
    _write_csv(rows, out_dir / "链接清单.csv")
    pending = _write_pending(rows, out_dir / "链接清单-待导入.txt")
    filtered = sum(1 for r in rows if r["category"] == "非营销")
    return {"total": len(rows), "pending": len(pending), "filtered": filtered}


def mark_done(target=None) -> int:
    """把待导入快照里的链接标记为已推送。返回新标记数。
    target=None 全标；int N 标前 N 批；str 公众号名 只标该号的所有待导入批次。"""
    if not PENDING_FILE.exists():
        print("没有待导入快照，先跑一次 export 生成 链接清单-待导入.txt 再标记。")
        return 0
    snapshot = json.loads(PENDING_FILE.read_text(encoding="utf-8"))   # [{account,links}]
    if isinstance(target, int):
        chosen = snapshot[:target]
    elif isinstance(target, str):
        chosen = [b for b in snapshot if b["account"] == target]
        if not chosen:
            accts = sorted({b["account"] for b in snapshot})
            print(f"待导入里没有「{target}」。当前有：{', '.join(accts) or '（空）'}")
            return 0
    else:
        chosen = snapshot
    take = [link for b in chosen for link in b["links"]]
    pushed = _load_pushed()
    before = len(pushed)
    pushed.update(take)
    _save_json(PUSHED_FILE, sorted(pushed))
    return len(pushed) - before


def main() -> int:
    ap = argparse.ArgumentParser(description="导出素材库链接清单 + 待导入批次")
    ap.add_argument("-d", "--dir", default=str(ROOT / "素材库"),
                    help="素材库目录（默认 素材库/）")
    ap.add_argument("--done", nargs="?", const="all", default=None,
                    metavar="批数/公众号名",
                    help="标记已推送：--done 全标；--done 3 标前 3 批；"
                         "--done 示例公众号 只标该号。之后重建清单")
    args = ap.parse_args()

    if args.done is not None:
        if args.done == "all":
            target, scope = None, "全部待导入"
        elif args.done.isdigit():
            target, scope = int(args.done), f"前 {args.done} 批"
        else:
            target, scope = args.done, f"公众号「{args.done}」"
        n = mark_done(target)
        print(f"已把{scope}标记为已推送（新增 {n} 条）。重建清单中…")

    res = export(args.dir)
    print(f"清单已更新：共 {res['total']} 条，待导入 {res['pending']} 条 "
          f"→ 链接清单.md / .csv / -待导入.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
