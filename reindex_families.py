# -*- coding: utf-8 -*-
"""族级重抽：路由到 elsevier/agu 的全部文献用当前代码（继承 base 超集+救援）重提。
清旧行+旧图 -> 重提 -> 入库。4 线程、进程优先级 BELOW_NORMAL（不抢占前台使用）。"""

import sys
import os
import glob
import ctypes
import sqlite3
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    k32 = ctypes.windll.kernel32
    k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)
except Exception:
    pass

from engine import FigureExtractor, MiniLMEncoder, FigureDB, IMAGE_DIR
from indexer import get_zotero_items_with_pdfs
from adapters import get_adapter

FAMILIES = ("elsevier", "agu_wiley")


def main():
    papers = get_zotero_items_with_pdfs(limit=None)
    targets = [p for p in papers
               if p.get("journal") and get_adapter(p["journal"], None).name in FAMILIES]
    print(f"targets: {len(targets)}", flush=True)

    db = FigureDB()
    ex = FigureExtractor()
    enc = MiniLMEncoder()

    def redo(p):
        key = p["item_key"]
        conn = db.get_conn()
        ids = [r[0] for r in conn.execute("SELECT id FROM figures WHERE item_key=?", (key,)).fetchall()]
        if ids:
            try:
                conn.executemany("DELETE FROM fts_figures WHERE rowid=?", [(i,) for i in ids])
            except sqlite3.OperationalError:
                pass
            conn.execute("DELETE FROM figures WHERE item_key=?", (key,))
            conn.commit()
        conn.close()
        for fp in glob.glob(os.path.join(IMAGE_DIR, f"{key}_*")):
            try:
                os.remove(fp)
            except OSError:
                pass
        try:
            figs = ex.extract_from_pdf(p["pdf_path"], key, p["att_key"],
                                       p["title"], p["year"], p["journal"])
        except Exception as e:
            print(f"{key} ERR {str(e)[:60]}", flush=True)
            return
        for f in figs:
            f["embedding"] = enc.encode(f["caption"])
            f["journal_abbr"] = p.get("journal_abbr", "")
            f["authors"] = p.get("authors", "")
            db.insert_figure(f)
        print(f"{key} {p['journal'][:22]:22s} -> {len(figs)}", flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(redo, targets))
    print("REINDEX_FAMILIES_DONE", flush=True)


if __name__ == "__main__":
    main()
