
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


def _latin_token_forms(toks, is_query):
    """拉丁名 token 列表 → 形态集合。

    关键修正（2026-10-28）：原实现只假设 toks[0] 是姓，导致 "Xiao-zhong Huang"
    这类被连字符切成三段的西式名无法生成 "huangxiaozhong"（漏 3 篇实测）。
    现对「首词为姓」与「末词为姓」两种假设都生成形态，并额外生成
    姓+名首字母（含仅首字母一种），以支持 "X.Z. Huang" 这类缩写查询。
    """
    forms = set()
    n = len(toks)
    if n == 0:
        return forms
    if n == 1:
        forms.add(toks[0])
        return forms

    for surname_pos in (0, n - 1):
        surname = toks[surname_pos]
        given = [t for i, t in enumerate(toks) if i != surname_pos]
        if not given:
            continue
        given_full = "".join(given)
        given_spaced = " ".join(given)
        # 名 + 姓 / 姓 + 名（分写与连写）
        forms.add(given_spaced + " " + surname)
        forms.add(given_full + surname)
        forms.add(surname + " " + given_spaced)
        forms.add(surname + given_full)
        # 姓 + 名缩写形态：库侧无条件生成（供 "X.Z. Huang" 查询命中全文名）；
        # 查询侧仅当自身含单字母 token（真写了缩写）时生成，防全名互撞
        want_abbrev = (not is_query) or any(len(t) == 1 for t in toks)
        if want_abbrev:
            initials = "".join(t[0] for t in given if t)
            if initials:
                forms.add(surname + " " + initials)
                forms.add(surname + initials)
                forms.add(initials + " " + surname)
                forms.add(initials + surname)
            first_initial = given[0][0] if given and given[0] else ""
            if first_initial:
                # 缩写只写到首字母也能命中全文名（"X. Huang" ↔ "Xiaozhong Huang"）
                forms.add(surname + first_initial)
                forms.add(surname + " " + first_initial)

    if not is_query:
        # 库端额外保留单 token，允许用户只按姓或只按名搜
        forms.update(toks)
    return forms


def author_forms(name, is_query=False):
    """作者名 → 归一形态集合（全小写、无标点）。

    中文名：汉字原文 + 拼音全拼/分写/名姓翻转 + 姓与名首字母缩写。
    拉丁名：见 _latin_token_forms（覆盖两种姓氏位置与缩写形式）。
    当 is_query=True 且为全名时，不生成裸单姓，防止以全名搜姓造成泛化误伤。
    """
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
            # 姓 + 拼音首字母（黄小忠 -> huangxz）：只在库侧无条件生成；
            # 查询侧仅当用户真的写了缩写（含单字母 token）时生成，
            # 否则 唐丽雅 的 'tang ly' 会撞上 唐领余 的 'tang ly'（2026-10-28 回归实测）
            if not is_query:
                initials = "".join(p[0] for p in given if p)
                if initials:
                    forms.add(surname + initials)                # huangxz
                    forms.add(surname + " " + initials)          # huang xz
                    forms.add(initials + surname)                # xzhuang
                    forms.add(initials + " " + surname)          # xz huang
                forms.add(surname)                           # tang
                forms.add(cjk[0])                            # 唐
        elif len(cjk) == 1:
            forms.add(cjk)
            if _HAS_PINYIN:
                forms.add("".join(lazy_pinyin(cjk)))
        return forms

    # 拉丁名：去变音 → token 化
    latin = _strip_accents(name.lower())
    toks = [t for t in re.split(r"[^a-z0-9]+", latin) if t]
    return _latin_token_forms(toks, is_query)


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

    判据（2026-10-28 二次收紧）：
    1. 只认「完整词条边界」匹配 —— 两端必须是分隔符，杜绝 "Li Xiaozhong" 这类
       由两个无关作者的词条拼出来的假命中；
    2. 弱形态（len<4 且无 CJK）一律不采信，避免缩写误配。
    两侧形态都已在 author_forms 里穷举生成，因此无需子串兜底。
    """
    if not query or not authors_norm:
        return False
    qfs = query_forms(query)
    if not qfs:
        return False
    padded = f" / {authors_norm} / "
    for qf in qfs:
        has_cjk = any(_is_cjk(ch) for ch in qf)
        if len(qf) < 4 and not (has_cjk and len(qf) >= 1):
            continue
        for pat in (f" / {qf} / ", f"| {qf} / ", f"/ {qf} |", f"| {qf} |"):
            if pat in padded:
                return True
    return False