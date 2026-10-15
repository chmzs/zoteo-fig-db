# -*- coding: utf-8 -*-
"""
AGU / Wiley Publishing Adapter
Dedicated for AGU journals: Geophysical Research Letters (GRL), Journal of Geophysical Research (JGR),
Water Resources Research (WRR), Earth's Future, Paleoceanography and Paleoclimatology, etc.
"""

import re
import fitz
from .base import BaseAdapter


class AGUAdapter(BaseAdapter):
    name = "agu_wiley"

    AGU_KEYWORDS = [
        "Geophysical Research Letters", "Journal of Geophysical Research",
        "Water Resources Research", "Earth's Future", "Paleoceanography",
        "Global Biogeochemical Cycles", "Geochemistry, Geophysics, Geosystems",
        "Reviews of Geophysics", "AGU Advances", "Tectonics", "Radio Science"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if not journal:
            first_text = doc[0].get_text()[:600]
            return "american geophysical union" in first_text.lower() or "agu" in first_text.lower()
        j_lower = journal.lower()
        if "geophysical research" in j_lower or "agu" in j_lower:
            return True
        return any(k.lower() in j_lower for k in self.AGU_KEYWORDS)

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        blocks = page.get_text("blocks")
        captions = []
        # AGU standard style strictly spells out 'Figure 1.'
        pattern = re.compile(r"^(Figure\s+(\d+[a-zA-Z]?)|Fig\.\s*(\d+[a-zA-Z]?))[\.:\s]", re.IGNORECASE)

        for b in blocks:
            if b[6] == 0:
                txt = b[4].strip()
                if re.match(r"^(Table|Tab\.)\b", txt, re.IGNORECASE):
                    continue
                m = pattern.search(txt)
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
