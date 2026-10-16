# -*- coding: utf-8 -*-
"""
Elsevier Publishing Adapter
Dedicated for Elsevier earth science journals: Quaternary Science Reviews, Palaeo3,
Earth-Science Reviews, Journal of Hydrology, CATENA, Quaternary International, GPC, etc.
"""

import fitz
from .base import BaseAdapter
from family_rules import journal_family


class ElsevierAdapter(BaseAdapter):
    name = "elsevier"

    ELSEVIER_KEYWORDS = [
        "Quaternary Science Reviews", "Palaeogeography, Palaeoclimatology, Palaeoecology",
        "Earth-Science Reviews", "Journal of Hydrology", "CATENA", "Quaternary International",
        "Global and Planetary Change", "Geochimica et Cosmochimica Acta", "Sedimentary Geology",
        "Geomorphology", "Chemical Geology", "Precambrian Research", "Applied Geochemistry"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if journal:
            j_lower = journal.lower()
            if "elsevier" in j_lower or "pergamon" in j_lower:
                return True
            return journal_family(journal) == "elsevier"
        if doc is not None:
            return "elsevier" in doc[0].get_text()[:600].lower()
        return False
