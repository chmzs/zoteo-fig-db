# -*- coding: utf-8 -*-
"""全库毒 PDF 定位：逐页 get_text('blocks') 试探，记录抛异常 或 渲染失败的文献与页码。"""
import sys, os, json, glob
sys.path.insert(0, r'D:\Zotero\fig_db')
sys.stdout.reconfigure(encoding='utf-8')
import fitz
from concurrent.futures import ThreadPoolExecutor

items = {}
for f in glob.glob(r'D:\Zotero\fig_db\batch_tmp\*.items.json'):
    for x in json.load(open(f, encoding='utf-8')):
        items[x['item_key']] = x
from indexer import get_zotero_items_with_pdfs
for p in get_zotero_items_with_pdfs(limit=None):
    items[p['item_key']] = p   # 全集覆盖批次集
print('papers:', len(items), flush=True)

def probe(kv):
    k, p = kv
    bad = []
    try:
        doc = fitz.open(p['pdf_path'])
    except Exception as e:
        return (k, p.get('pdf_path',''), [('open', type(e).__name__)])
    for pi in range(len(doc)):
        try:
            doc[pi].get_text('blocks')
        except Exception as e:
            bad.append((pi + 1, type(e).__name__, str(e)[:60]))
            break  # 一篇记首个毒页即可
        try:
            doc[pi].get_drawings()
        except Exception as e:
            bad.append((pi + 1, type(e).__name__, str(e)[:60]))
            break
    doc.close()
    return (k, p.get('pdf_path',''), bad)

out = []
with ThreadPoolExecutor(max_workers=4) as pool:
    for k, path, bad in pool.map(probe, sorted(items.items())):
        if bad:
            out.append({'item_key': k, 'pdf': path, 'fail': bad})
            print('POISON', k, bad[:1], flush=True)
json.dump(out, open('poison_scan.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print('scan done, poison papers:', len(out), flush=True)
