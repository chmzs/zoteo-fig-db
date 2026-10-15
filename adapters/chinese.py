# -*- coding: utf-8 -*-
"""
Chinese Geoscience Journals Adapter
Dedicated for Chinese journals: 地理学报, 第四纪研究, 中国科学:地球科学, 科学通报, etc.
Handles bilingual caption pairing (图 1 + Fig. 1) and CJK punctuation.
"""

import re
import fitz
from .base import BaseAdapter


class ChineseJournalsAdapter(BaseAdapter):
    name = "chinese_journals"

    CHINESE_JOURNAL_KEYWORDS = [
        "地理学报", "第四纪研究", "中国科学", "科学通报", "地质学报",
        "沉积学报", "古地理学报", "地球化学", "生态学报", "气候与环境研究",
        "高原气象", "冰川冻土", "湖泊科学", "ACTA GEOGRAPHICA SINICA",
        "QUATERNARY SCIENCES", "SCIENCE CHINA"
    ]

    def match(self, journal: str, doc: fitz.Document) -> bool:
        if not journal:
            # Check metadata or first page text
            first_text = doc[0].get_text()[:600]
            return any(k in first_text for k in self.CHINESE_JOURNAL_KEYWORDS)
        j_upper = journal.upper()
        return any(k.upper() in j_upper for k in self.CHINESE_JOURNAL_KEYWORDS)

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        blocks = page.get_text("blocks")
        raw_captions = []
        fig_pattern = re.compile(
            r"^(Figure\s+(\d+[a-zA-Z]?)|Fig\.\s*(\d+[a-zA-Z]?)|图\s*(\d+[a-zA-Z]?)|附图\s*(\d+[a-zA-Z]?))[\.:\s|]",
            re.IGNORECASE,
        )

        for b in blocks:
            if b[6] == 0:
                txt = b[4].strip()
                if re.match(r"^(Table|Tab\.|表)\b", txt, re.IGNORECASE):
                    continue
                m = fig_pattern.search(txt)
                if m:
                    matched_str = m.group(1).strip()
                    num_m = re.search(r"\d+[a-zA-Z]?", matched_str)
                    fig_num = num_m.group(0).lower() if num_m else matched_str
                    caption_text = txt.replace("\n", " ").strip()
                    is_zh = matched_str.startswith("图") or matched_str.startswith("附图")

                    raw_captions.append({
                        "fig_no": matched_str,
                        "fig_num": fig_num,
                        "is_zh": is_zh,
                        "caption": caption_text,
                        "rect": fitz.Rect(b[0], b[1], b[2], b[3]),
                    })

        if not raw_captions:
            # 块首全空时落到 base：行首救援 + 跨块纯标签行（扫描 OCR 层/混排版式）
            return super().find_captions(page, page_idx)

        # Merge bilingual pairs (Chinese '图 N' + English 'Fig. N')
        merged_by_num = {}
        for rc in raw_captions:
            num = rc["fig_num"]
            if num not in merged_by_num:
                merged_by_num[num] = rc
            else:
                existing = merged_by_num[num]
                if existing["is_zh"] and not rc["is_zh"]:
                    existing["fig_no"] = f"{existing['fig_no']} ({rc['fig_no']})"
                    existing["caption"] = f"{existing['caption']} | {rc['caption']}"
                elif not existing["is_zh"] and rc["is_zh"]:
                    existing["fig_no"] = f"{rc['fig_no']} ({existing['fig_no']})"
                    existing["caption"] = f"{rc['caption']} | {existing['caption']}"
                existing["rect"] = existing["rect"] | rc["rect"]

        return list(merged_by_num.values())
