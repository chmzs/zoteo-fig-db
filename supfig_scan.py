# -*- coding: utf-8 -*-
"""全库词式 SI 检测: PDF 含 Supplementary/Extended Data Figure 编号 -> supfig_targets.json"""
import sys, os, re, json, time
sys.path.insert(0, r'D:\Zotero\fig_db')
sys.stdout.reconfigure(encoding='utf-8')
import fitz
from concurrent.futures import ThreadPoolExecutor
from indexer import get_zotero_items_with_pdfs

PAT = re.compile(r'(?:Supplementary|Supplemental|Appendix|Extended\s+Data)\s+(?:Figure|Fig\.?)\s*\d', re.I)

def check(p):
    try:
        doc = fitz.open(p['pdf_path'])
    except Exception:
        return p['item_key']   # 打不开=重提候选
    hit = None
    try:
        n = len(doc)
        for pi in range(min(11, n), n):
            try:
                if PAT.search(doc[pi].get_text()):
                    hit = p['item_key']; break
            except Exception:
                hit = p['item_key']; break
    finally:
        doc.close()
    return hit

papers = [p for p in get_zotero_items_with_pdfs(limit=None) if p.get('pdf_path')]
print('papers:', len(papers), flush=True)
t0 = time.time(); keys = []; done = 0
import sqlite3
c = sqlite3.connect(r'D:\Zotero\fig_db\zotero-figures.sqlite')
stamp = dict(c.execute("SELECT item_key, MAX(extractor_version) FROM figures GROUP BY item_key").fetchall())
c.close()
with ThreadPoolExecutor(max_workers=4) as pool:
    for k in pool.map(check, papers):
        done += 1
        if k: keys.append(k)
        if done % 250 == 0: print(f'  {done}/{len(papers)} ({time.time()-t0:.0f}s) 命中{len(keys)}', flush=True)
stale = [k for k in keys if stamp.get(k, '0.0') != '2.0']
json.dump({'keys': stale, 'found': len(keys)}, open(r'D:\Zotero\fig_db\supfig_targets.json', 'w'))
print(f'scan done {time.time()-t0:.0f}s: 词式SI篇={len(keys)} 需重提(非2.0戳)={len(stale)}', flush=True)
