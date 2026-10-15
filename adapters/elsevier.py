# -*- coding: utf-8 -*-
"""
Elsevier Publishing Adapter
Dedicated for Elsevier earth science journals: Quaternary Science Reviews, Palaeo3,
Earth-Science Reviews, Journal of Hydrology, CATENA, Quaternary International, GPC, etc.
"""

import re
import fitz
from .base import BaseAdapter


class ElsevierAdapter(BaseAdapter):
    name = "elsevier"

    ELSEVIER_KEYWORDS = [
        "Quaternary Science Reviews", "Palaeogeography, Palaeoclimatology, Palaeoecology",
        "Earth-Science Reviews", "Journal of Hydrology", "CATENA", "Quaternary International",
        "Global and Planetary Change", "Geochimica et Cosmochimica Acta", "Sedimentary Geology",
        "Geomorphology", "Chemical Geology", "Precambrian Research", "Applied Geochemistry"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if not journal:
            first_text = doc[0].get_text()[:600]
            return "elsevier" in first_text.lower()
        j_lower = journal.lower()
        if "elsevier" in j_lower:
            return True
        return any(k.lower() in j_lower for k in self.ELSEVIER_KEYWORDS)

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        blocks = page.get_text("blocks")
        captions = []
        # Elsevier uses 'Fig. 1.' or 'Figure 1.'
        pattern = re.compile(r"^(Fig\.\s*(\d+[a-zA-Z]?)|Figure\s+(\d+[a-zA-Z]?))[\.:\s]", re.IGNORECASE)

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
