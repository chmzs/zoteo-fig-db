# -*- coding: utf-8 -*-
"""
Generic Fallback Adapter
Handles all other publishers (AAAS/Science, Springer, Copernicus, SAGE, MDPI, etc.)
using generalized vector path and raster bounding box fusion.
"""

from .base import BaseAdapter


class GenericAdapter(BaseAdapter):
    name = "generic"

    def match(self, journal: str, doc: fitz.Document) -> bool:
        # Fallback always matches
        return True
