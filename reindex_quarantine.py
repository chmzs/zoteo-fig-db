# -*- coding: utf-8 -*-
"""主批跑完后执行：读取 batch_state.json + batch_tmp/*.quarantine.jsonl 的隔离条目，
用当前最新代码重跑（修复 get_drawings 降级后可救回大部分 MuPDF 异常文献）。"""
import sys, os, json, glob
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from engine import FigureExtractor, Encoder, FigureDB
from indexer import get_zotero_items_with_pdfs

def main():
    keys = set()
    st_file = os.path.join(BASE_DIR, "batch_state.json")
    if os.path.exists(st_file):
        for q in json.load(open(st_file, encoding="utf-8")).get("quarantined", []):
            keys.add(q.get("item_key"))
    for f in glob.glob(os.path.join(BASE_DIR, "batch_tmp", "*.quarantine.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                keys.add(json.loads(line)["item_key"])
            except Exception:
                pass
    keys.discard(None)
    print(f"quarantined keys: {len(keys)}")

    db = FigureDB()
    conn = db.get_conn()
    in_db = {r[0] for r in conn.execute("SELECT DISTINCT item_key FROM figures")}
    conn.close()
    targets = keys - in_db
    print(f"still missing from DB: {len(targets)}")
    if not targets:
        return

    papers = {p["item_key"]: p for p in get_zotero_items_with_pdfs(limit=None)}
    extractor = FigureExtractor(); encoder = Encoder()
    ok = fail = 0
    for k in targets:
        p = papers.get(k)
        if not p:
            print("  no main PDF:", k); fail += 1; continue
        try:
            figs = extractor.extract_from_pdf(p["pdf_path"], k, p["att_key"], p["title"], p["year"], p["journal"])
            for f in figs:
                f["embedding"] = encoder.encode(f["caption"])
                f["journal_abbr"] = p.get("journal_abbr", "")
                f["authors"] = p.get("authors", "")
                db.insert_figure(f)
            print(f"  {k} -> {len(figs)} figs"); ok += 1
        except Exception as e:
            print(f"  {k} STILL FAIL: {str(e)[:90]}"); fail += 1
    print(f"done ok={ok} fail={fail}")

if __name__ == "__main__":
    main()
