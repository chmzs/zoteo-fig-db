"""
Reindex all existing items with current extractor logic.
- 清理假图注残留行（题注被并入正文的假卡）
- 重抽全部图并补 journal_abbr / authors 新列
"""

import glob
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from engine import IMAGE_DIR, Encoder, FigureDB, FigureExtractor
from indexer import get_zotero_items_with_pdfs


def main():
    # 清掉磁盘检索缓存（列结构已变，必须重建）
    for f in (os.path.join(BASE_DIR, "cache", "embed_matrix.npy"),
              os.path.join(BASE_DIR, "cache", "embed_meta.pkl")):
        if os.path.exists(f):
            os.remove(f)

    db = FigureDB()
    conn = db.get_conn()
    cur = conn.cursor()
    existing = [r[0] for r in cur.execute("SELECT DISTINCT item_key FROM figures").fetchall()]
    conn.close()

    papers = {p["item_key"]: p for p in get_zotero_items_with_pdfs(limit=400)}

    extractor = FigureExtractor()
    encoder = Encoder()

    total = 0
    for key in existing:
        p = papers.get(key)
        if not p:
            print(f"[{key}] 找不到主 PDF，保留旧行")
            continue

        # 清旧行 + 旧图文件
        conn = db.get_conn()
        ids = [r[0] for r in conn.execute("SELECT id FROM figures WHERE item_key=?", (key,)).fetchall()]
        if ids:
            try:
                conn.executemany("DELETE FROM fts_figures WHERE rowid=?", [(i,) for i in ids])
            except sqlite3.OperationalError:
                pass  # external-content FTS 不允许直接 DELETE；陈旧 rowid 由 id2idx 过滤，无影响
        conn.execute("DELETE FROM figures WHERE item_key=?", (key,))
        conn.commit()
        conn.close()
        for fpath in glob.glob(os.path.join(IMAGE_DIR, f"{key}_*")):
            try:
                os.remove(fpath)
            except OSError:
                pass

        figs = extractor.extract_from_pdf(
            pdf_path=p["pdf_path"], item_key=key, att_key=p["att_key"],
            title=p["title"], year=p["year"], journal=p["journal"],
        )
        for f in figs:
            f["embedding"] = encoder.encode(f["caption"])
            f["journal_abbr"] = p.get("journal_abbr", "")
            f["authors"] = p.get("authors", "")
            db.insert_figure(f)

        print(f"[{key}] {p['journal']} -> {len(figs)} figs (abbr={p.get('journal_abbr','')!r}, authors={p.get('authors','')!r})")
        total += len(figs)

    stats = db.get_stats()
    print(f"\nDone. reindexed {total} figs; DB now {stats}")


if __name__ == "__main__":
    main()
