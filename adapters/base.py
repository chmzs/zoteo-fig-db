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
        band = fitz.Rect(cx0, 45.0, cx1, cap_rect.y0)
        if band.height < 60:
            return None, None

        band_imgs = [vi for vi in valid_images
                     if vi["rect"] and vi["rect"].intersects(band) and vi["rect"].y1 <= cap_rect.y0 + 15]
        band_dr = [d["rect"] for d in page_drawings
                   if d["rect"].y1 <= cap_rect.y0 + 12 and d["rect"].y0 >= 40 and d["rect"].intersects(band)]

        # 单幅位图且无矢量叠加 → 直接抽原始字节（最常见，最高保真）
        if len(band_imgs) == 1 and not band_dr:
            return None, band_imgs[0]

        parts = [vi["rect"] for vi in band_imgs] + band_dr
        if not parts:
            # 题注上方没有图形证据：假题注（正文交叉引用/图注块被并进正文）
            return None, None

        u = parts[0]
        for r in parts[1:]:
            u = u | r

        # 合并图形近旁的文本标注：刻度数字、轴单位、面板字母 (a)(b)、色标文字
        # （懒计算：仅矢量渲染分支会解码整页文本层；位图直抽路径零成本）
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
            exp = fitz.Rect(u.x0 - 20, u.y0 - 14, u.x1 + 20, u.y1 + 10)
            for sr in spans:
                if sr.y0 >= 40 and sr.y1 <= cap_rect.y0 - 2 and sr.intersects(exp):
                    u = u | sr

        clip = fitz.Rect(
            max(25, u.x0 - 6),
            max(40, u.y0 - 6),
            min(page_rect.width - 25, u.x1 + 6),
            min(cap_rect.y0 - 2, u.y1 + 6),
        )
        if clip.height < 60 or clip.width < 80:
            return band, None
        return clip, None
