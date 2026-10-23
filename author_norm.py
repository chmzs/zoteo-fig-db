
"""author_norm.py — 作者名归一化（中文 ↔ 拼音英文名模糊匹配）。

设计修复（2026-10-23 实测）：
- author_forms(name) 用于建立库端形态集：包含全名、拼音连写、名姓翻转，以及单字姓/单字拼音（允许用单字姓去查多字名）。
- query_forms(query) 用于查询：
  1. 如果用户输入完整名字（如 >=2 汉字 '唐丽雅' 或多 token 拉丁名 'Tang Liya'），
     查询形态只保留全名和全拼变体，严禁回退到单姓 '唐'/'tang'（否则搜 '唐丽雅' 会误中所有姓唐的作者 '唐领余'）！
  2. 只有当用户确实只输入单姓（如 '唐' 或单 token 'Tang'）时，才按单姓匹配。
"""

import re
import unicodedata

_HAS_PINYIN = True
try:
    from pypinyin import lazy_pinyin
except Exception:
    _HAS_PINYIN = False


def _strip_accents(s):
    """去变音符：é→e, ü→u（NFD 分解后丢组合符）。"""
    return "".join(ch for ch in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(ch))


def _is_cjk(ch):
    return "\u4e00" <= ch <= "\u9fff"


def _clean(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (s or "").lower()).strip()


def author_forms(name, is_query=False):
    """作者名 → 归一形态集合（全小写、无标点）。
    当 is_query=True 且 name 为全名（>=2 汉字或多 token）时，不生成单姓，防止以名搜姓泛化误伤。"""
    name = (name or "").strip()
    if not name:
        return set()
    forms = set()
    if any(_is_cjk(ch) for ch in name):
        cjk = "".join(ch for ch in name if _is_cjk(ch))
        forms.add(cjk)                       # 原文：唐丽雅
        if _HAS_PINYIN and len(cjk) >= 2:
            pys = lazy_pinyin(cjk)           # ['tang','li','ya']
            surname, given = pys[0], pys[1:]
            forms.add("".join(pys))                          # tangliya
            forms.add(" ".join(pys))                         # tang li ya
            forms.add("".join(given) + surname)              # liyatang
            forms.add(" ".join(given) + " " + surname)       # liya tang
            if not is_query:
                # 库端建立索引形态时保留姓，允许用户单搜姓
                forms.add(surname)                           # tang
                forms.add(cjk[0])                            # 唐
        elif len(cjk) == 1:
            forms.add(cjk)
            if _HAS_PINYIN:
                pys = lazy_pinyin(cjk)
                forms.add("".join(pys))
        return forms

    # 拉丁名：去变音 → token 化 → 翻转/连写
    latin = _strip_accents(name.lower())
    toks = [t for t in re.split(r"[^a-z0-9]+", latin) if t]
    if not toks:
        return set()
    forms.add(" ".join(toks))                # marie auger methe
    forms.add("".join(toks))                 # marieaugermethe
    if len(toks) >= 2:
        forms.add(" ".join(toks[1:] + toks[:1]))
        forms.add("".join(toks[1:] + toks[:1]))
        if not is_query:
            # 库端保留首尾 token，允许用户单搜 surname
            forms.add(toks[0])
            forms.add(toks[-1])
    else:
        forms.add(toks[0])
    return forms


def build_authors_norm(author_list):
    """全部作者 → 单列存储串：各作者形态以 ' | ' 分隔，形态内以 ' / ' 区分。"""
    parts = []
    for a in author_list or []:
        fs = author_forms(a, is_query=False)
        if fs:
            parts.append(" / ".join(sorted(fs)))
    return " | ".join(parts)


def query_forms(query):
    """查询词归一 → 形态集合（全名不降级为单姓）。"""
    return author_forms(query, is_query=True)


def author_match(query, authors_norm):
    """查询是否命中 authors_norm 串。
    库端以 ' / ' 或 ' | ' 分隔各词条形态。精准匹配 token 块避免子串错配。"""
    if not query or not authors_norm:
        return False
    qfs = query_forms(query)
    if not qfs:
        q_clean = _clean(query)
        return f"/ {q_clean} /" in f"/ {authors_norm} /" or f"| {q_clean} |" in f"| {authors_norm} |"
    
    # 包装 authors_norm 便于完全匹配单元
    padded = f" / {authors_norm} / "
    for qf in qfs:
        target = f" / {qf} / "
        if target in padded or f"| {qf} /" in padded or f"/ {qf} |" in padded or f"| {qf} |" in padded:
            return True
        # 兜底：两字以上连续字符直接子串命中
        if len(qf) >= 3 and qf in authors_norm:
            return True
    return False
