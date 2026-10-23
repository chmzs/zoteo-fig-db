"""族级重抽：路由到指定家族的文献用当前代码重提。

2026-10-21 夜跑前加固（三处，均由实测驱动）：
1. 先抽取后清场——原实现先 DELETE 再 extract，extract 抛异常时该篇图净丢且无标记
   （实测复现：样本篇 4 行 -> 0 行）。改为 extract 成功拿到结果才清旧行，失败则原样保留。
2. 逐篇完成标记 .reindex_done/<item_key>——家族级哨兵太粗，中途死要整族重跑；
   现按篇续跑，重启只补未完成的。
3. 单线程——实测 6 线程比单线程慢 28%（0.72x，GIL+线程开销，fitz 是 CPU 密集），
   且 poison_scan 的历史事故表明 MuPDF 并发有 longjmp 风险，单线程两条都规避。

用法: python reindex_families.py elsevier[,agu_wiley,nature_portfolio] | all | <keys.json>
"""

import ctypes
import glob
import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    k32 = ctypes.windll.kernel32
    k32.SetProcessPriorityBoost(k32.GetCurrentProcess(), True)  # 不抢占前台（Win8+ 有效）
    k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)   # BELOW_NORMAL_PRIORITY_CLASS
except Exception:
    pass

from adapters import get_adapter
from engine import IMAGE_DIR, Encoder, FigureDB, FigureExtractor
from indexer import get_zotero_items_with_pdfs

FAMILIES = tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else ("elsevier", "agu_wiley")
DONE_DIR = os.path.join(BASE_DIR, "batch_tmp", "reindex_done")
PROGRESS_EVERY = 25


def _marker(item_key):
    return os.path.join(DONE_DIR, item_key)


def main():
    os.makedirs(DONE_DIR, exist_ok=True)
    papers = get_zotero_items_with_pdfs(limit=None)
    if FAMILIES and FAMILIES[0].endswith(".json"):
        d = json.load(open(FAMILIES[0], encoding="utf-8"))
        keys = set(d["keys"]) if isinstance(d, dict) else set(d)
        targets = [p for p in papers if p["item_key"] in keys]
    elif FAMILIES and FAMILIES[0] == "all":
        targets = [p for p in papers if p.get("pdf_path")]
    else:
        targets = [p for p in papers
                   if p.get("journal") and get_adapter(p["journal"], None).name in FAMILIES]

    total = len(targets)
    todo = [p for p in targets if not os.path.exists(_marker(p["item_key"]))]
    print(f"targets: {total}  todo: {len(todo)}  (已标记完成 {total - len(todo)})", flush=True)

    db = FigureDB()
    ex = FigureExtractor()
    enc = Encoder()

    ok = fail = 0
    for i, p in enumerate(todo, 1):
        key = p["item_key"]
        # ---- 1. 先抽取（失败则一行不动，旧数据原样保留）----
        try:
            figs = ex.extract_from_pdf(p["pdf_path"], key, p["att_key"],
                                       p["title"], p["year"], p["journal"])
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(todo)}] {key} EXTRACT_FAIL {str(e)[:70]}", flush=True)
            continue
        if figs is None:
            figs = []

        # 抽取成功才清场（删行 + 删旧图文件）。
        # 关键：extract_from_pdf 在抽取时已写出新图文件，清场只能删"不在新结果里的旧文件"，
        # 否则会把刚写出的新图一并删掉（2026-10-23 夜跑实测回归：6685 个 v2.1 行图片全丢）。
        conn = db.get_conn()
        ids = [r[0] for r in conn.execute("SELECT id FROM figures WHERE item_key=?", (key,)).fetchall()]
        if ids:
            try:
                conn.executemany("DELETE FROM fts_figures WHERE rowid=?", [(i2,) for i2 in ids])
            except sqlite3.OperationalError:
                pass
            conn.execute("DELETE FROM figures WHERE item_key=?", (key,))
            conn.commit()
        conn.close()
        new_files = {os.path.basename(f["image_path"]) for f in figs if f.get("image_path")}
        # 缩略图同名派生（xxx.webp -> xxx.thumb.webp）
        new_files |= {fn[:-5] + ".thumb.webp" for fn in new_files if fn.endswith(".webp")}
        for fp in glob.glob(os.path.join(IMAGE_DIR, f"{key}_*")):
            if os.path.basename(fp) in new_files:
                continue  # 新抽取写出的文件，保留
            try:
                os.remove(fp)
            except OSError:
                pass

        # ---- 2. 入库（逐条，单条失败不拖垮整篇）----
        written = 0
        for f in figs:
            try:
                f["embedding"] = enc.encode(f["caption"])
                f["journal_abbr"] = p.get("journal_abbr", "")
                f["authors"] = p.get("authors", "")
                f["context_text"] = p.get("abstract") or ""
                db.insert_figure(f)
                written += 1
            except Exception as e:
                print(f"[{i}/{len(todo)}] {key} INSERT_FAIL fig={f.get('fig_no')} {str(e)[:60]}", flush=True)

        # ---- 3. 逐篇完成标记（下次运行跳过）----
        with open(_marker(key), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"item_key": key, "figs": written,
                                 "panel": sum(1 for x in figs if x.get("origin") == "panel")},
                                ensure_ascii=False))
        ok += 1
        if i % PROGRESS_EVERY == 0 or i == len(todo):
            print(f"[{i}/{len(todo)}] 进度 ok={ok} fail={fail} 最近={key} "
                  f"{p['journal'][:20]} -> {written} figs", flush=True)
        else:
            print(f"[{i}/{len(todo)}] {key} {p['journal'][:20]:20s} -> {written}", flush=True)

    print(f"REINDEX_FAMILIES_DONE ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
