"""panel_qc.py — 面板级切分灰度 QC（只读干跑：不写主 DB、不碰服务）。

用法：
  python panel_qc.py --keys JYGMPNRM,97LJ8KDF,UJ5TQUQP
  python panel_qc.py --family elsevier --limit 50
产物：batch_tmp/panel_qc/
  <ITEM>_<FIG>_parent.webp            整图（既有路径原样）
  <ITEM>_<FIGpanel>.webp              面板裁图
  <ITEM>_<FIG>_overlay.png            父图上叠面板框（目视判误切用）
  report.jsonl                        每行一篇：题注/面板数/字母/bbox/尺寸
"""
import argparse
import glob
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import fitz
from PIL import Image, ImageDraw

from adapters import get_adapter
from engine import FigureExtractor

QC_DIR = os.path.join(BASE_DIR, "batch_tmp", "panel_qc")


def locate_main_pdf(item_key):
    """从既有 DB 行拿 (主 PDF 路径, journal)。"""
    import sqlite3
    conn = sqlite3.connect("file:" + os.path.join(BASE_DIR, "zotero-figures.sqlite") + "?mode=ro", uri=True)
    rows = conn.execute("SELECT DISTINCT att_key, journal FROM figures WHERE item_key=?",
                        (item_key,)).fetchall()
    conn.close()
    journal = ""
    for (att_key, journal) in rows:
        folder = os.path.join(r"D:\Zotero\storage", att_key)
        for f in sorted(glob.glob(os.path.join(folder, "*.pdf"))):
            if re.search(r"supplement|translation|双语|沉浸式", f, re.I):
                continue
            return f, journal
    return None, journal


def overlay(page, region, panels, path):
    """父区域渲染 + 面板框叠加（页坐标 z=2 渲染，框用不同色区分）。"""
    z = 2.0
    pix = page.get_pixmap(clip=region, matrix=fitz.Matrix(z, z), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    d = ImageDraw.Draw(im)
    palette = [(230, 40, 40), (40, 120, 230), (30, 180, 90), (230, 140, 20),
               (150, 60, 200), (200, 40, 160), (60, 170, 180), (120, 120, 30)]
    for i, p in enumerate(panels):
        r = p["rect"]
        box = ((r.x0 - region.x0) * z, (r.y0 - region.y0) * z,
               (r.x1 - region.x0) * z, (r.y1 - region.y0) * z)
        col = palette[i % len(palette)]
        d.rectangle(box, outline=col, width=3)
        d.text((box[0] + 4, box[1] + 3), p["letter"], fill=col)
    im.save(path, "PNG")


def qc_paper(item_key, pdf_path, journal, report, force=False):
    ex = FigureExtractor(output_dir=QC_DIR)
    doc = fitz.open(pdf_path)
    adapter = get_adapter(journal, doc)
    if force:
        adapter.panel_split = True  # 越界探针：临时打开（不触生产开关）
    n_panel_imgs = 0
    for page_idx in range(min(len(doc), 120)):
        page = doc[page_idx]
        caps = adapter.find_captions(page, page_idx)
        if not caps:
            continue
        infos = page.get_image_info(xrefs=True)
        valid_images, seen = [], set()
        for info in infos:
            xref = info.get("xref")
            if xref is None or xref in seen:
                continue
            w, h = info.get("width", 0), info.get("height", 0)
            if w >= 200 and h >= 160:
                seen.add(xref)
                bb = info.get("bbox")
                valid_images.append({"xref": xref, "w": w, "h": h,
                                     "rect": fitz.Rect(bb) if bb else None})
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []
        for cap in caps:
            if re.search(r"[.…·]{4,}", cap["caption"]):
                continue
            clip_rect, matched_raster = adapter.locate_figure_box(
                page=page, cap_rect=cap["rect"], valid_images=valid_images,
                page_drawings=drawings, all_captions=caps)
            if not adapter.panel_split or re.search(r"[a-zA-Z]$", cap["fig_no"]):
                continue
            region = clip_rect if clip_rect is not None else (
                matched_raster["rect"] if matched_raster else None)
            if region is None or region.width < 120 or region.height < 120:
                continue
            raster = None
            dom = max((vi for vi in valid_images if vi["rect"] and (vi["rect"] & region).is_valid
                       and (vi["rect"] & region).get_area() / max(1.0, region.get_area()) >= 0.60),
                      key=lambda vi: (vi["rect"] & region).get_area(), default=None)
            if dom is not None:
                from PIL import Image as _I
                import io as _io
                try:
                    _im = _I.open(_io.BytesIO(doc.extract_image(dom["xref"])["image"])).convert("RGB")
                    raster = {"image": _im, "rect": dom["rect"]}
                except Exception:
                    raster = None
            panels = adapter.detect_panels(page=page, fig_rect=region, valid_images=valid_images,
                                           page_drawings=drawings, parent_caption=cap["caption"],
                                           raster=raster)
            if not panels:
                continue
            fig_slug = re.sub(r"[^\w\d]", "_", cap["fig_no"])
            op = os.path.join(QC_DIR, f"{item_key}_{fig_slug}_overlay.png")
            overlay(page, region, panels, op)
            rows = []
            for pl in panels:
                p_fig = f"{cap['fig_no']}{pl['letter']}"
                p_name = f"{item_key}_{re.sub('[^A-Za-z0-9]', '_', p_fig)}_p{page_idx + 1}.webp"
                p_path = os.path.join(QC_DIR, p_name)
                ok = ex._save_panel(doc, page, pl, valid_images, {}, p_path)
                size = None
                if ok:
                    n_panel_imgs += 1
                    with Image.open(p_path) as im:
                        size = im.size
                rows.append({"letter": pl["letter"], "fig_no": p_fig, "saved": bool(ok),
                             "source": pl.get("source", "label"),
                             "bbox_pt": [round(v, 1) for v in (pl["rect"].x0, pl["rect"].y0,
                                                               pl["rect"].x1, pl["rect"].y1)],
                             "px": list(size) if size else None,
                             "caption": pl["caption"][:120]})
            report.append({"item_key": item_key, "page": page_idx + 1, "parent_fig": cap["fig_no"],
                           "parent_caption": cap["caption"][:200], "n_panels": len(panels),
                           "region_pt": [round(v, 1) for v in (region.x0, region.y0, region.x1, region.y1)],
                           "overlay": os.path.basename(op), "panels": rows})
    doc.close()
    return n_panel_imgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--family", default="")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--force", action="store_true",
                    help="越界探针：临时对目标适配器开启 panel_split（仅 QC，不改生产）")
    a = ap.parse_args()
    os.makedirs(QC_DIR, exist_ok=True)

    keys = [k.strip() for k in a.keys.split(",") if k.strip()]
    if not keys and a.family:
        from indexer import get_zotero_items_with_pdfs
        keys = [p["item_key"] for p in get_zotero_items_with_pdfs(limit=None)
                if p.get("journal") and get_adapter(p["journal"], None).name == a.family]
        # 只取有主 PDF 的前 N 篇
        keys = [k for k in keys if locate_main_pdf(k)[0]][: a.limit]
        print(f"family={a.family} targets={len(keys)}", flush=True)

    report = []
    total = 0
    for k in keys:
        pdf, journal = locate_main_pdf(k)
        if not pdf:
            print(f"{k} NO-PDF", flush=True)
            continue
        try:
            n = qc_paper(k, pdf, journal, report, force=a.force)
        except Exception as e:
            print(f"{k} ERR {str(e)[:80]}", flush=True)
            continue
        total += n
        print(f"{k} panels={n}", flush=True)
    with open(os.path.join(QC_DIR, "report.jsonl"), "w", encoding="utf-8") as f:
        for r in report:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    figs = len(report)
    print(f"\nQC DONE: {figs} 个多联父图 / {total} 张面板 / report -> {os.path.join(QC_DIR, 'report.jsonl')}")


if __name__ == "__main__":
    main()
