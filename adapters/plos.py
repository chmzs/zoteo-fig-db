# -*- coding: utf-8 -*-
r"""
PLOS Publisher Adapter (PLOS ONE / PLOS Biology / PLOS Medicine ...)
特化点：题注句式 "Fig 1. xxx"——"Fig" 与数字之间没有点，数字后才有句点。
base 超集要求 Fig. 带反斜杠点（Fig 带点）→ PLOS 题注全部漏配。本适配器把锚点改为
"Fig(可无点)\s*\d+..." 且数字后必须紧跟句点——正文引用样式
"Fig 3 presented..."（数字后是空格）天然被排除。
"""

import re
import fitz

from .base import BaseAdapter


class PLOSAdapter(BaseAdapter):
    name = "plos"

    PLOS_MARKS = ("plos", "public library of science")

    def match(self, journal: str, doc: fitz.Document) -> bool:
        j = (journal or "").lower()
        if any(k in j for k in self.PLOS_MARKS):
            return True
        if not journal:
            first = doc[0].get_text()[:600].lower()
            return "plos one" in first
        return False

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        blocks = page.get_text("blocks")
        captions = []
        # "Fig 1." / "Figure 1." / "图1."：数字后紧跟句点才算题注
        fig_pat = re.compile(
            r"^(Figure|Fig\.?|图)\s*(\d+[a-zA-Z]?)\.(?=[\s|]|$)",
            re.IGNORECASE,
        )
        for b in blocks:
            if b[6] != 0:
                continue
            txt = b[4].strip()
            if re.match(r"^(Table|Tab\.|表)\b", txt, re.IGNORECASE):
                continue
            m = fig_pat.search(txt)
            if m:
                matched_str = m.group(0).strip()
                fig_num = m.group(2).lower()
                captions.append({
                    "fig_no": matched_str,
                    "fig_num": fig_num,
                    "caption": txt.replace("\n", " ").strip(),
                    "rect": fitz.Rect(b[0], b[1], b[2], b[3]),
                })
        return captions
