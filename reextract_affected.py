"""受影响论文重抽：旋转页 + 竖长条可疑图（2026-11-15）。

背景：修了两处通用几何缺陷——
  1) rotation≠0 页归零（横向大图只裁一半）
  2) 裁剪框被正文文字块主导时拒绝（整段正文被当图）
本脚本按可判定判据挑出受影响论文并重抽：remove → extract → insert。
**顺序铁律**：remove_item 会删除 DB 行与图片文件，必须先删后抽。

判据（任一命中即重抽）：
  A. 该篇任一张图所在页面 rotation != 0（旋转页裁偏）
  C. 该篇任一条题注是续行（"Fig. N continued."）——真题注在前页，需回填
  B. 该篇任一条题注是"正文句式"（编号后无句点、紧跟 shows/presents/plots 等）
     —— 这类题注会把正文段落当图体。
注：试过"竖长条（高>1.6×宽）"判据，抽查两张均为合法竖图（5 面板柱状图、三阶段概念图），
已作废——形状不能当缺陷判据，只能当人工筛查信号。

用法：python reextract_affected.py [--limit N] [--reset]
可续跑：游标存 cache/reextract_state.json。跑完需删 cache/embed_* 并重启 server。
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re

import fitz
from PIL import Image

CONTINUED_STYLE = re.compile(
    r"^(?:Fig(?:ure)?\.?)\s*\d+[a-z]?\s*[.:]?\s*\(?\s*continued\s*\)?\.?$", re.I)

BODY_STYLE = re.compile(
    r"^(?:Fig(?:ure)?\.?)\s*\d+[a-z]?\s+"
    # 不含 plot/plots："Fig. 5 Plot showing ..." 是合法题注写法（2A3J2WW9 实测误判）
    r"(shows|show|presents|present|illustrates|illustrate|displays|display|depicts|depict|indicates|indicate|summariz|summaris)",
    re.I,
)

from engine import DB_PATH, Encoder, FigureDB, FigureExtractor

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "reextract_state.json")


def is_strip(path):
    try:
        with Image.open(path) as im:
            w, h = im.size
        return h > w * 1.6
    except Exception:
        return False


def has_rotated_page(pdf_path, page_numbers):
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False
    try:
        for page_no in page_numbers:
            if 1 <= page_no <= len(doc) and doc[page_no - 1].rotation:
                return True
        return False
    finally:
        doc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40, help="本次处理多少篇（含未受影响）")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    cursor = 0
    if os.path.exists(STATE_PATH) and not args.reset:
        try:
            cursor = int(json.load(open(STATE_PATH, encoding="utf-8")).get("cursor", 0))
        except (ValueError, OSError):
            cursor = 0

    conn = sqlite3.connect(DB_PATH, timeout=60)
    papers = conn.execute(
        "SELECT item_key, att_key, COUNT(*) FROM figures GROUP BY item_key, att_key"
        " ORDER BY item_key").fetchall()
    total = len(papers)
    window = papers[cursor:cursor + args.limit]
    print(f"papers={total} cursor={cursor} window={len(window)}")

    db = FigureDB()
    extractor = FigureExtractor()
    encoder = Encoder()

    affected = 0
    for item_key, att_key, _n in window:
        row = conn.execute(
            "SELECT title, year, journal, journal_abbr, authors, authors_norm, context_text"
            " FROM figures WHERE item_key=? LIMIT 1", (item_key,)).fetchone()
        if not row:
            continue
        title, year, journal, abbr, authors, anorm, ctx = row
        rows = conn.execute(
            "SELECT page_no, image_path, COALESCE(caption,'') FROM figures WHERE item_key=?",
            (item_key,)).fetchall()
        pages = [r[0] for r in rows if r[0]]
        body_style = sum(1 for r in rows if BODY_STYLE.match(r[2]))
        continued = sum(1 for r in rows if CONTINUED_STYLE.match((r[2] or "").strip()))
        pdfs = glob.glob(os.path.join("D:/Zotero/storage", att_key or "", "*.pdf"))
        rotated = has_rotated_page(pdfs[0], pages) if pdfs else False

        if not (rotated or body_style or continued):
            continue

        affected += 1
        before_rows = len(rows)
        before_strips = body_style
        if not pdfs:
            print(f"  [skip] {item_key} 无 PDF")
            continue
        db.remove_item(item_key)
        figs = extractor.extract_from_pdf(
            pdf_path=pdfs[0], item_key=item_key, att_key=att_key,
            title=title or "", year=year or 0, journal=journal or "")
        for fig in figs:
            fig["embedding"] = encoder.encode(fig["caption"])
            fig["journal_abbr"] = abbr or ""
            fig["authors"] = authors or ""
            fig["context_text"] = ctx or ""
            fig["authors_norm"] = anorm or ""
            db.insert_figure(fig)
        after_strips = sum(1 for f in figs if BODY_STYLE.match(f.get("caption") or ""))
        missing = sum(1 for f in figs if not os.path.exists(f["image_path"]))
        flag = (("旋转" if rotated else "") + ("+正文题注" if body_style else "")
                + ("+续行题注" if continued else ""))
        print(f"  {item_key:10s} {flag:2s} rows {before_rows}->{len(figs)}  "
              f"正文题注 {before_strips}->{after_strips}  missing={missing}  {str(journal)[:30]}", flush=True)

    cursor += len(window)
    with open(STATE_PATH, "w", encoding="utf-8") as state_file:
        json.dump({"cursor": cursor, "updated_at": time.time()}, state_file)
    print(f"done window: affected={affected} next_cursor={cursor}/{total}")
    conn.close()


if __name__ == "__main__":
    main()
