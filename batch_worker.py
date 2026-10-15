# -*- coding: utf-8 -*-
"""Batch worker: 提取一组文献的图并入库。
用法: python batch_worker.py <items.json> <out_prefix>
每篇一行 JSON 写 <out>.papers.jsonl（供断点核对）；异常写 quarantine；批次 QC 写 <out>.qc.json
"""

import sys
import os
import json
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import FigureExtractor, MiniLMEncoder, FigureDB
from PIL import Image


def bbox_sanity(img_path):
    try:
        with Image.open(img_path) as im:
            w, h = im.size
        if w < 300 or h < 300:
            return True
        if max(w, h) / max(1, min(w, h)) > 5.5:
            return True
    except Exception:
        return True
    return False


def main():
    items_file, out_prefix = sys.argv[1], sys.argv[2]
    items = json.load(open(items_file, encoding="utf-8"))

    extractor = FigureExtractor()
    encoder = MiniLMEncoder()
    db = FigureDB()

    n_figs = 0
    n_zero = 0
    n_extreme = 0
    t0 = time.time()

    with open(out_prefix + ".papers.jsonl", "w", encoding="utf-8") as fp, \
         open(out_prefix + ".quarantine.jsonl", "a", encoding="utf-8") as fq:
        for p in items:
            t1 = time.time()
            try:
                figs = extractor.extract_from_pdf(
                    pdf_path=p["pdf_path"],
                    item_key=p["item_key"],
                    att_key=p.get("att_key", ""),
                    title=p.get("title", ""),
                    year=p.get("year", 0),
                    journal=p.get("journal", ""),
                )
                for f in figs:
                    f["embedding"] = encoder.encode(f["caption"])
                    f["journal_abbr"] = p.get("journal_abbr", "")
                    f["authors"] = p.get("authors", "")
                    db.insert_figure(f)
                    if bbox_sanity(f["image_path"]):
                        n_extreme += 1
                n_figs += len(figs)
                if not figs:
                    n_zero += 1
                fp.write(json.dumps({
                    "item_key": p["item_key"],
                    "journal": p.get("journal", ""),
                    "figs": len(figs),
                    "secs": round(time.time() - t1, 2),
                }, ensure_ascii=False) + "\n")
            except Exception as e:
                fq.write(json.dumps({
                    "item_key": p["item_key"],
                    "pdf": p.get("pdf_path", ""),
                    "err": f"{type(e).__name__}: {str(e)[:180]}",
                }, ensure_ascii=False) + "\n")
                fp.write(json.dumps({
                    "item_key": p["item_key"], "journal": p.get("journal", ""),
                    "figs": 0, "err": 1,
                }, ensure_ascii=False) + "\n")
            fp.flush()

    qc = {
        "papers": len(items),
        "figs": n_figs,
        "zero_figs_papers": n_zero,
        "extreme_bbox": n_extreme,
        "secs": round(time.time() - t0, 1),
    }
    with open(out_prefix + ".qc.json", "w", encoding="utf-8") as f:
        json.dump(qc, f, ensure_ascii=False)
    print("QC " + json.dumps(qc, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
