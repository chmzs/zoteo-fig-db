# -*- coding: utf-8 -*-
"""稳定版全库毒 PDF 探查：单进程顺序探查，彻底免疫 MuPDF 多线程 longjmp 崩溃。
每 200 篇打印进度，实时存入 poison_scan.json，完成调用 make_poison_report。"""
import sys, os, glob, json, fitz, time

sys.path.insert(0, r'D:\Zotero\fig_db')
sys.stdout.reconfigure(encoding='utf-8')
from indexer import get_zotero_items_with_pdfs

items = {}
for p in get_zotero_items_with_pdfs(limit=None):
    items[p['item_key']] = p

papers = sorted(items.items())
print(f"Total papers: {len(papers)}", flush=True)

OUT_FILE = r'D:\Zotero\fig_db\poison_scan.json'

# 加载已有结果（如果存在）
poison_dict = {}
if os.path.exists(OUT_FILE):
    try:
        for x in json.load(open(OUT_FILE, encoding='utf-8')):
            poison_dict[x['item_key']] = x
    except:
        pass

t0 = time.time()
for i, (k, p) in enumerate(papers):
    pdf = p.get('pdf_path', '')
    if not pdf or not os.path.exists(pdf):
        poison_dict[k] = {'item_key': k, 'pdf': pdf, 'fail': [('open', 'FileNotFoundError', 'PDF file not found')]}
        continue
    try:
        doc = fitz.open(pdf)
    except Exception as e:
        poison_dict[k] = {'item_key': k, 'pdf': pdf, 'fail': [('open', type(e).__name__, str(e)[:80])]}
        continue
    
    bad = []
    try:
        max_pages = min(len(doc), 120)
        for pi in range(max_pages):
            try:
                doc[pi].get_text('blocks')
            except Exception as e:
                bad.append((pi + 1, type(e).__name__, str(e)[:80]))
                break
    except Exception as e:
        bad.append((0, type(e).__name__, str(e)[:80]))
    finally:
        try:
            doc.close()
        except:
            pass
            
    if bad:
        poison_dict[k] = {'item_key': k, 'pdf': pdf, 'fail': bad}
        print(f"POISON [{i+1}/{len(papers)}] {k} -> {bad[0]}", flush=True)
        json.dump(list(poison_dict.values()), open(OUT_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    if (i + 1) % 500 == 0:
        print(f"  scanned {i+1}/{len(papers)} ({time.time()-t0:.1f}s, total_poison={len(poison_dict)})", flush=True)

json.dump(list(poison_dict.values()), open(OUT_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"scan done, poison papers: {len(poison_dict)} in {time.time()-t0:.1f}s", flush=True)

try:
    import make_poison_report
    make_poison_report.main()
    print("poison_report.md updated successfully!", flush=True)
except Exception as e:
    print(f"Failed to generate report: {e}", flush=True)
