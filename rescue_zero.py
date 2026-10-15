# -*- coding: utf-8 -*-
"""主批完成后：收集所有 figs==0 的论文，用当前最新代码重跑，救回可提取的图。"""
import sys, os, json, glob
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from engine import FigureExtractor, MiniLMEncoder, FigureDB
from indexer import get_zotero_items_with_pdfs

def main():
    zero_keys = set()
    for f in glob.glob(os.path.join(BASE_DIR, "batch_tmp", "*.papers.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
                if o.get("figs") == 0 and not o.get("err"):
                    zero_keys.add(o["item_key"])
            except Exception:
                pass
    db = FigureDB()
    conn = db.get_conn()
    have = {r[0] for r in conn.execute("SELECT DISTINCT item_key FROM figures WHERE fig_no != ''")}
    conn.close()
    targets = sorted(zero_keys - have)
    print(f"zero-fig papers: {len(zero_keys)}, still empty: {len(targets)}")
    if not targets:
        return
    papers = {p['item_key']: p for p in get_zotero_items_with_pdfs(limit=None)}
    ex, enc = FigureExtractor(), MiniLMEncoder()
    n_rescued = n_still = 0
    for k in targets:
        p = papers.get(k)
        if not p:
            n_still += 1; continue
        try:
            figs = ex.extract_from_pdf(p['pdf_path'], k, p['att_key'], p['title'], p['year'], p['journal'])
        except Exception:
            n_still += 1; continue
        if figs:
            for fg in figs:
                fg['embedding'] = enc.encode(fg['caption'])
                fg['journal_abbr'] = p.get('journal_abbr', '')
                fg['authors'] = p.get('authors', '')
                db.insert_figure(fg)
            n_rescued += 1
        else:
            n_still += 1
    print(f"rescued {n_rescued} papers, still zero {n_still}")

if __name__ == "__main__":
    main()
