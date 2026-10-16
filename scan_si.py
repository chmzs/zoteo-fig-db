# -*- coding: utf-8 -*-
"""定向扫描：找出需要 v1.9 重提的文献——S编号题注（Figure S1/图S2）或页数>60（曾被截断）。
输出 si_targets.json = {"keys":[...], "stat":{...}}"""
import sys
import os
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.stdout.reconfigure(encoding='utf-8')

import fitz
from indexer import get_zotero_items_with_pdfs

S_PAT = re.compile(r"(?:Figure|Fig\.?)\s*S\d|图\s*S\d|附图\s*S\d", re.I)


CHECKPOINT = os.path.join(BASE, "scan_checkpoint.json")


def check(p):
    """返回 (key, kind)：kind in {'S','long',None}"""
    try:
        doc = fitz.open(p["pdf_path"])
    except Exception:
        return (p["item_key"], None)
    try:
        n = len(doc)
        if n > 60:
            return (p["item_key"], "long")
        for pi in range(min(9, n), n):  # SI 都在前几页正文之后
            try:
                if S_PAT.search(doc[pi].get_text()):
                    return (p["item_key"], "S")
            except Exception:
                return (p["item_key"], "S")  # 读不动的 PDF 一律重提兜底
        return (p["item_key"], None)
    finally:
        doc.close()


def main():
    papers = [p for p in get_zotero_items_with_pdfs(limit=None) if p.get("pdf_path")]
    print(f"papers: {len(papers)}", flush=True)
    t0 = time.time()
    keys_s, keys_long = [], []
    done = 0
    seen = set()
    ck_s, ck_l = [], []
    if os.path.exists(CHECKPOINT):
        try:
            ck = json.load(open(CHECKPOINT, encoding='utf-8'))
            seen = set(ck.get('done', [])); ck_s = ck.get('S', []); ck_l = ck.get('long', [])
        except Exception:
            pass
    papers = [p for p in papers if p['item_key'] not in seen]
    print(f'resumed, remaining: {len(papers)}', flush=True)
    keys_s, keys_long = list(ck_s), list(ck_l)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for key, kind in pool.map(check, papers):
            done += 1
            if kind == "S":
                keys_s.append(key)
            elif kind == "long":
                keys_long.append(key)
            seen.add(key)
            if done % 200 == 0:
                json.dump({'done': sorted(seen | set(keys_s) | set(keys_long) | {key}), 'S': keys_s, 'long': keys_long}, open(CHECKPOINT, 'w', encoding='utf-8'))
                print(f"  scanned {done}/{len(papers)} ({time.time()-t0:.0f}s) S={len(keys_s)} long={len(keys_long)}", flush=True)
    out = {"keys": sorted(set(keys_s) | set(keys_long)),
           "stat": {"S": len(keys_s), "long": len(keys_long),
                    "both": len(set(keys_s) & set(keys_long)),
                    "total": len(set(keys_s) | set(keys_long))}}
    json.dump(out, open(os.path.join(BASE, "si_targets.json"), "w", encoding="utf-8"))
    print(f"scan done in {time.time()-t0:.0f}s:", out["stat"], flush=True)


if __name__ == "__main__":
    main()
