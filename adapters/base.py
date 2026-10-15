# -*- coding: utf-8 -*-
"""
Base Publisher Adapter for Zotero GeoFigure Engine
Defines the interface for publisher-specific PDF layout adapters.
"""

import re
import fitz


class BaseAdapter:
    """Base class for all publisher-specific PDF layout adapters."""
    name = "base"

    def match(self, journal: str, doc: fitz.Document) -> bool:
        """Return True if this adapter handles the journal/publisher."""
        return False

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        """
        Extract caption text blocks from a page.
        Returns: list of dicts: {'fig_no': str, 'fig_num': str, 'caption': str, 'rect': fitz.Rect}
        """
        blocks = page.get_text("blocks")
        captions = []
        fig_pattern = re.compile(
            r"^(Figure\s+(\d+[a-zA-Z]?)|Fig\.\s*(\d+[a-zA-Z]?)|图\s*(\d+[a-zA-Z]?)|附图\s*(\d+[a-zA-Z]?))[\.:\s|]",
            re.IGNORECASE,
        )

        for b in blocks:
            if b[6] == 0:  # text
                txt = b[4].strip()
                if re.match(r"^(Table|Tab\.|表)\b", txt, re.IGNORECASE):
                    continue
                m = fig_pattern.search(txt)
                if m:
                    matched_str = m.group(1).strip()
                    num_m = re.search(r"\d+[a-zA-Z]?", matched_str)
                    fig_num = num_m.group(0).lower() if num_m else matched_str
                    caption_text = txt.replace("\n", " ").strip()
                    captions.append({
                        "fig_no": matched_str,
                        "fig_num": fig_num,
                        "caption": caption_text,
                        "rect": fitz.Rect(b[0], b[1], b[2], b[3]),
                    })
        return captions

    def locate_figure_box(self, page: fitz.Page, cap_rect: fitz.Rect, valid_images: list,
                          page_drawings: list, text_spans: list = None) -> tuple:
        """定位题注上方的图形区域。返回 (clip Rect 或 None, 命中位图 dict 或 None)。

        原则：宁宽勿裁，但绝不盲裁。
        - 位图证据优先（原始字节最高保真）；
        - 矢量图取 路径∪位图∪紧邻文本标注 并集（刻度数字/单位/(a)(b) 不被裁掉）；
        - 题注上方无任何图形证据 → 拒绝（杀掉"正文交叉引用被当题注"的假图卡）。
        """
        page_rect = page.rect
        is_left = cap_rect.x1 < page_rect.width * 0.55
        is_right = cap_rect.x0 > page_rect.width * 0.45
        is_full = cap_rect.width > page_rect.width * 0.55

        if is_left and not is_full:
            cx0, cx1 = 35.0, page_rect.width * 0.52
        elif is_right and not is_full:
            cx0, cx1 = page_rect.width * 0.48, page_rect.width - 35.0
        else:
            cx0, cx1 = 35.0, page_rect.width - 35.0

        # ---- 主路径：图形在题注上方（绝大多数出版商）----
        band = fitz.Rect(cx0, 45.0, cx1, cap_rect.y0)
        band_imgs, band_dr = [], []
        if band.height >= 60:
            band_imgs = [vi for vi in valid_images
                         if vi["rect"] and vi["rect"].intersects(band) and vi["rect"].y1 <= cap_rect.y0 + 15]
            band_dr = [d["rect"] for d in page_drawings
                       if d["rect"].y1 <= cap_rect.y0 + 12 and d["rect"].y0 >= 40 and d["rect"].intersects(band)]

            # 单幅位图且无矢量叠加 → 直接抽原始字节（最常见，最高保真）
            if len(band_imgs) == 1 and not band_dr:
                return None, band_imgs[0]

        parts = [vi["rect"] for vi in band_imgs] + band_dr
        if parts:
            u = parts[0]
            for r in parts[1:]:
                u = u | r
            u = self._merge_spans(page, u, text_spans, 40.0, cap_rect.y0 - 2, 14.0, 10.0)
            clip = fitz.Rect(
                max(25, u.x0 - 6),
                max(40, u.y0 - 6),
                min(page_rect.width - 25, u.x1 + 6),
                min(cap_rect.y0 - 2, u.y1 + 6),
            )
            if clip.height < 60 or clip.width < 80:
                return band, None
            return clip, None

        # ---- 回退路径：题注在图上方（Wiley Accepted Article 等手稿式排版）----
        # 题注块高 <220pt：防"图注并入正文长块"的假题注从下方误捕
        if (cap_rect.y1 - cap_rect.y0) < 220:
            clip_b, raster_b = self._figure_below_caption(
                page, cap_rect, valid_images, page_drawings, text_spans, cx0, cx1)
            if clip_b is not None or raster_b is not None:
                return clip_b, raster_b

        # ---- 回退路径：题注与图左右并排（老刊侧置图注版式；限窄题注块）----
        if cap_rect.width < page_rect.width * 0.5:
            clip_s, raster_s = self._figure_beside_caption(
                page, cap_rect, valid_images, page_drawings, text_spans)
            if clip_s is not None or raster_s is not None:
                return clip_s, raster_s

        # 两个方向都没有图形证据：假题注，拒绝，绝不盲裁
        return None, None

    def _merge_spans(self, page, u, text_spans, y_top, y_bottom, pad_above, pad_below):
        """合并图形近旁的文本标注：刻度数字、轴单位、面板字母 (a)(b)、色标文字（懒计算）。"""
        spans = text_spans
        if spans is None:
            try:
                spans = [
                    fitz.Rect(s["bbox"])
                    for blk in page.get_text("dict")["blocks"]
                    for line in blk.get("lines", [])
                    for s in line.get("spans", [])
                ]
            except Exception:
                spans = []
        elif callable(spans):
            spans = spans()
        if spans:
            exp = fitz.Rect(u.x0 - 20, u.y0 - pad_above, u.x1 + 20, u.y1 + pad_below)
            for sr in spans:
                if sr.y0 >= y_top and sr.y1 <= y_bottom and sr.intersects(exp):
                    u = u | sr
        return u

    def _figure_below_caption(self, page, cap_rect, valid_images, page_drawings, text_spans, cx0, cx1):
        """题注下方的紧邻图形：位图起点距题注底 ≤60pt 直抽；矢量簇向下生长收全竖排面板。"""
        page_rect = page.rect
        bottom_lim = min(page_rect.height - 35.0, cap_rect.y1 + 460.0)
        band = fitz.Rect(cx0, max(40.0, cap_rect.y1 - 8.0), cx1, bottom_lim)
        if band.height < 60:
            return None, None

        cands = [vi for vi in valid_images
                 if vi["rect"] and vi["rect"].intersects(band)
                 and cap_rect.y1 - 12 <= vi["rect"].y0 <= cap_rect.y1 + 60
                 and vi["rect"].height <= 520]
        if cands:
            cands.sort(key=lambda vi: vi["rect"].y0 - cap_rect.y1)
            return None, cands[0]

        drs = [d["rect"] for d in page_drawings
               if d["rect"].intersects(band) and cap_rect.y1 - 12 <= d["rect"].y0 <= cap_rect.y1 + 60]
        if not drs:
            return None, None
        u = drs[0]
        for r in drs[1:]:
            u = u | r
        grew, guard = True, 0
        while grew and guard < 12:
            grew, guard = False, guard + 1
            for d in page_drawings:
                r = d["rect"]
                if r.intersects(band) and u.y0 - 10 <= r.y0 <= u.y1 + 14 and r.y1 > u.y1:
                    u = u | r
                    grew = True
        u = self._merge_spans(page, u, text_spans, max(40.0, cap_rect.y1 - 2), bottom_lim, 14.0, 16.0)
        clip = fitz.Rect(max(25, u.x0 - 6), max(cap_rect.y1 - 2, u.y0 - 6),
                         min(page_rect.width - 25, u.x1 + 6), min(bottom_lim + 8, u.y1 + 6))
        return clip, None

    def _figure_beside_caption(self, page, cap_rect, valid_images, page_drawings, text_spans):
        """题注与图左右并排（老刊侧置图注/双联版式）。
        守卫：仅窄题注块（调用方限制）、位图与题注纵向重叠 >=35%、距题注边 <=320pt、
        排除整页扫描与超大 union，防误捕相邻联内容。"""
        page_rect = page.rect
        for side in ("right", "left"):
            if side == "right":
                win = fitz.Rect(cap_rect.x1 + 2, max(40.0, cap_rect.y0 - 25),
                                min(page_rect.width - 25, cap_rect.x1 + 320.0),
                                cap_rect.y1 + 25)
                near = lambda r: r.x0 >= cap_rect.x1 - 12
            else:
                win = fitz.Rect(max(25.0, cap_rect.x0 - 320.0), max(40.0, cap_rect.y0 - 25),
                                cap_rect.x0 - 2, cap_rect.y1 + 25)
                near = lambda r: r.x1 <= cap_rect.x0 + 12
            if win.x1 - win.x0 < 80 or win.y1 - win.y0 < 60:
                continue
            side_imgs = []
            for vi in valid_images:
                r = vi["rect"]
                if not r or not near(r) or r.height > 540:
                    continue
                if not r.intersects(win):
                    continue
                ov = min(r.y1, win.y1) - max(r.y0, win.y0)
                if ov > 0 and ov / max(1.0, r.height) >= 0.35:
                    side_imgs.append(vi)
            side_dr = [d["rect"] for d in page_drawings
                       if near(d["rect"]) and d["rect"].intersects(win) and d["rect"].y0 >= 40]
            if len(side_imgs) == 1 and not side_dr:
                return None, side_imgs[0]
            parts = [vi["rect"] for vi in side_imgs] + side_dr
            if not parts:
                continue
            u = parts[0]
            for r in parts[1:]:
                u = u | r
            if (u.y1 - u.y0) > 560:
                continue
            u = self._merge_spans(page, u, text_spans, 40.0, page_rect.height - 40.0, 12.0, 12.0)
            clip = fitz.Rect(max(25, u.x0 - 6), max(40, u.y0 - 6),
                             min(page_rect.width - 25, u.x1 + 6),
                             min(page_rect.height - 40, u.y1 + 6))
            if clip.height >= 60 and clip.width >= 80:
                return clip, None
        return None, None
