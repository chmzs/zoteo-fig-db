"""
AGU / Wiley Publishing Adapter
Dedicated for AGU journals: Geophysical Research Letters (GRL), Journal of Geophysical Research (JGR),
Water Resources Research (WRR), Earth's Future, Paleoceanography and Paleoclimatology, etc.
"""

import fitz

from family_rules import journal_family

from .base import BaseAdapter


class AGUAdapter(BaseAdapter):
    name = "agu_wiley"
    panel_split = True  # 多联图重灾区，标签网格+证据链可守

    AGU_KEYWORDS = [
        "Geophysical Research Letters", "Journal of Geophysical Research",
        "Water Resources Research", "Earth's Future", "Paleoceanography",
        "Global Biogeochemical Cycles", "Geochemistry, Geophysics, Geosystems",
        "Reviews of Geophysics", "AGU Advances", "Tectonics", "Radio Science"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if journal:
            j_lower = journal.lower()
            if "geophysical research" in j_lower or "agu" in j_lower or "agupubs" in j_lower:
                return True
            return journal_family(journal) == "agu"
        if doc is not None:
            first_text = doc[0].get_text()[:600].lower()
            return "american geophysical union" in first_text or "agu" in first_text
        return False
