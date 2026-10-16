# -*- coding: utf-8 -*-
"""毒 PDF 用户介入报告：poison_scan.json / poison_failures.json -> poison_report.md

分级与处置：
- 文件丢失/损坏/加密 = 只有用户能修（Zotero 里重新链接/下载/解密）
- 毒页(MuPDF图形栈)   = 程序已自愈(页级容错)，仅在需要毒页图时才建议换工具重拼
"""
import os
import json
import re
import time
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "poison_report.md")

ACTIONS = [
    (re.compile(r"FileNotFoundError", re.I),
     "文件丢失", "附件在磁盘上已不存在（被移动/删除/storage 目录改名）——在 Zotero 中重新关联或重新下载该 PDF"),
    (re.compile(r"encrypt|password|needs pass", re.I),
     "加密 PDF", "带口令保护——去除口令后重新导入（或用出版商未加密原稿）"),
    (re.compile(r"graphics states", re.I),
     "毒页（MuPDF 限制）", "无需介入：页级容错已跳过毒页、整篇其余图已入库；仅当需要毒页上的图时，用其他工具重新合并该 PDF 或下载出版商原始分件"),
    (re.compile(r"IndexError|not in document|cannot open|structure|corrupt", re.I),
     "文件损坏", "PDF 结构异常——从出版商重新下载原件替换 Zotero 附件"),
]


def classify(err):
    for pat, cls, act in ACTIONS:
        if pat.search(err):
            return cls, act
    return "其他异常", "人工检查"


def rows():
    out = []
    p = os.path.join(BASE, "poison_scan.json")
    if os.path.exists(p):
        for x in json.load(open(p, encoding="utf-8")):
            parts = []
            for f in x.get("fail", []):
                pg, typ = f[0], f[1]
                msg = f[2] if len(f) > 2 else ""
                parts.append(f"p{pg}:{typ} {msg}" if pg != "open" else f"open:{typ} {msg}")
            out.append((x["item_key"], x.get("pdf", ""), "; ".join(parts)[:120]))
    p = os.path.join(BASE, "poison_failures.json")
    if os.path.exists(p):
        for item in json.load(open(p, encoding="utf-8")):
            k, t, err = item[0], item[1] if len(item) > 1 else "", item[2]
            out.append((k, t, err))
    return out


def main():
    items = rows()
    c = sqlite3.connect(os.path.join(BASE, "zotero-figures.sqlite"))
    buckets = {}
    seen = set()
    for k, ref, err in items:
        if k in seen:
            continue
        seen.add(k)
        cls, act = classify(err)
        r = c.execute("SELECT title, journal FROM figures WHERE item_key=? LIMIT 1", (k,)).fetchone()
        if not r:
            r = (ref if ref and not ref.lower().endswith(".pdf") else k, "")
        buckets.setdefault(cls, []).append((k, (r[0] or "")[:70], r[1] or "", err[:90], act))
    c.close()

    lines = ["# 毒 PDF 用户介入报告", "",
             f"生成：{time.strftime('%Y-%m-%d %H:%M')} · 异常篇数：{len(seen)}", ""]
    order = ["文件丢失", "文件损坏", "加密 PDF", "毒页（MuPDF 限制）", "其他异常"]
    for cls in order:
        if cls not in buckets:
            continue
        need_me = cls != "毒页（MuPDF 限制）"
        lines.append(f"## {cls}（{len(buckets[cls])} 篇）" + ("　⚠需你处理" if need_me else "　✔程序已自愈"))
        lines.append("")
        for k, t, j, err, act in buckets[cls]:
            lines.append(f"- [{k}](zotero://select/library/items/{k}) {t}（{j}）")
            lines.append(f"  - 错误：`{err}`")
            lines.append(f"  - 处置：{act}")
        lines.append("")
    if not seen:
        lines.append("（暂无异常——扫描干净）")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    print("poison_report.md 写出:", {cls: len(buckets[cls]) for cls in buckets}, flush=True)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
