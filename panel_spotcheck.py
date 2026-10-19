"""panel_spotcheck.py — 从主库面板行出目视联系表（明晨 §八.3 抽检用）。

每父图一行：整图缩略 + 各面板裁图缩略，标 fig_no 与 px。
用法: python panel_spotcheck.py [--sample 12] [--out batch_tmp/spotcheck]
"""
import argparse
import json
import os
import random
import re
import sqlite3
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, "D:/Zotero/fig_db")
from engine import DB_PATH

ap = argparse.ArgumentParser()
ap.add_argument("--sample", type=int, default=12)
ap.add_argument("--out", default="D:/Zotero/fig_db/batch_tmp/spotcheck")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
parents = {}
for ik, fn, img in conn.execute(
        "SELECT item_key, fig_no, image_path FROM figures WHERE origin='whole'"):
    parents.setdefault(ik, {})[fn] = img
rows = []
for ik, pfn, pj, pimg in conn.execute(
        "SELECT item_key, fig_no, panels_json, image_path FROM figures WHERE origin='panel'"):
    d = json.loads(pj)
    rows.append((ik, d["parent_fig"], pfn, pimg, d))

if not rows:
    print("库中暂无面板行（夜跑后重查）")
    sys.exit(0)

by_parent = {}
for r in rows:
    by_parent.setdefault((r[0], r[1]), []).append(r)
keys = sorted(by_parent)
random.seed(7)
sample = random.sample(keys, min(a.sample, len(keys)))
print(f"面板父图共 {len(keys)}，抽检 {len(sample)}")

for ik, pfn in sample:
    panels = sorted(by_parent[(ik, pfn)], key=lambda r: r[4].get("letter", r[2]))
    wk_path = parents.get(ik, {}).get(pfn)
    cells = []
    if wk_path and os.path.exists(wk_path):
        im = Image.open(wk_path).convert("RGB")
        im.thumbnail((420, 420))
        cells.append((pfn, im))
    for _ik, _p, fig_no, pimg, _d in panels:
        if pimg and os.path.exists(pimg):
            im = Image.open(pimg).convert("RGB")
            im.thumbnail((300, 300))
            cells.append((fig_no, im))
    if not cells:
        continue
    H = max(c[1].height for c in cells) + 22
    W = sum(c[1].width + 8 for c in cells) + 8
    canvas = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(canvas)
    x = 8
    for label, im in cells:
        canvas.paste(im, (x, 22))
        d.text((x + 2, 6), f"{ik} {label}", fill=(0, 0, 0))
        d.rectangle([x - 2, 20, x + im.width + 2, 22 + im.height], outline=(200, 60, 60))
        x += im.width + 8
    slug = re.sub(r"[^\w]", "_", f"{ik}_{pfn}")
    out = f"{a.out}/{slug}_sheet.png"
    canvas.save(out)
    print("  ", out, canvas.size)
conn.close()
