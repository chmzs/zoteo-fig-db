"""
Publisher Adapters Registry for Zotero GeoFigure Engine
"""

from .agu import AGUAdapter
from .base import BaseAdapter
from .chinese import ChineseJournalsAdapter
from .elsevier import ElsevierAdapter
from .generic import GenericAdapter
from .nature import NatureAdapter
from .plos import PLOSAdapter

# Order matters: specific adapters first, GenericAdapter as fallback
ADAPTER_REGISTRY = [
    ChineseJournalsAdapter(),
    NatureAdapter(),
    ElsevierAdapter(),
    AGUAdapter(),
    PLOSAdapter(),
    GenericAdapter(),
]


def get_adapter(journal: str, doc) -> BaseAdapter:
    """Return the first matching publisher adapter for a document."""
    for adapter in ADAPTER_REGISTRY:
        try:
            if adapter.match(journal, doc):
                return adapter
        except Exception:
            pass
    return ADAPTER_REGISTRY[-1]
