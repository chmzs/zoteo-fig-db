"""
Nature Publishing Group Adapter
Dedicated for Nature, Nature Communications, Nature Geoscience, Nature Climate Change, etc.
Handles Nature's distinct 'Fig. X | ...' caption syntax and grid layout.
"""

import re

import fitz

from family_rules import journal_family

from .base import BaseAdapter


class NatureAdapter(BaseAdapter):
    name = "nature_portfolio"

    NATURE_KEYWORDS = [
        "Nature", "Nat Commun", "Nat. Commun.", "Nature Communications",
        "Nat Geosci", "Nature Geoscience", "Nat Clim Chang", "Nature Climate Change",
        "Nat Ecol Evol", "Nature Ecology & Evolution", "Scientific Reports"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if not journal:
            first_text = doc[0].get_text()[:600]
            return "nature" in first_text.lower()
        j_lower = journal.lower()
        if any(k.lower() in j_lower for k in self.NATURE_KEYWORDS):
            return True
        return journal_family(journal) == "nature"

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        blocks = page.get_text("blocks")
        captions = []
        # Nature strictly uses 'Fig. X | ' or 'Figure X | '
        nature_pattern = re.compile(r"^(Fig\.\s*(\d+[a-zA-Z]?)|Figure\s+(\d+[a-zA-Z]?))\s*\|", re.IGNORECASE)

        for b in blocks:
            if b[6] == 0:
                txt = b[4].strip()
                m = nature_pattern.search(txt)
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

        # Fallback to base pattern if none matched with pipe
        if not captions:
            return super().find_captions(page, page_idx)

        return captions
