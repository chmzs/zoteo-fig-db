"""
Notes Map: item_key -> Obsidian Zotero 笔记双链 (确定性扫描)
文件名规则: <year>_<作者>_<标题截断>_KEY-<itemKey>.md
别名: frontmatter 的 aliases 行 (如 'Grinnell, 1917, Auk')
映射不到笔记时退化为 zotero://select 的 markdown 链接
"""

import json
import os
import re
import time

NOTES_DIR = r"D:\Users\chmzs\Documents\PaperBell\01_输入\Zotero笔记"
CACHE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "notes_map.json")

KEY_RE = re.compile(r"KEY-([A-Z0-9]{8})\.md$")


def build_notes_map():
    mapping = {}
    if not os.path.isdir(NOTES_DIR):
        return mapping
    for fname in os.listdir(NOTES_DIR):
        if not fname.endswith(".md"):
            continue
        m = KEY_RE.search(fname)
        if not m:
            continue
        item_key = m.group(1)
        note_name = fname[:-3]  # strip .md
        aliases = ""
        try:
            fpath = os.path.join(NOTES_DIR, fname)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                # Only read frontmatter (first ~800 chars is enough)
                head = f.read(800)
            am = re.search(r"^aliases:\s*(.+)$", head, re.MULTILINE)
            if am:
                aliases = am.group(1).strip()
        except Exception:
            pass
        mapping[item_key] = {"note_name": note_name, "aliases": aliases}
    return mapping


_map_cache = None
_map_loaded_at = 0


def get_notes_map(force_refresh=False):
    global _map_cache, _map_loaded_at
    now = time.time()
    if not force_refresh and _map_cache is not None and (now - _map_loaded_at) < 600:
        return _map_cache

    # Try load from json cache
    loaded = None
    if not force_refresh and os.path.exists(CACHE_JSON):
        try:
            with open(CACHE_JSON, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if (now - cached.get("built_at", 0)) < 86400:  # daily refresh
                loaded = cached.get("map", {})
        except Exception:
            loaded = None

    if loaded is None:
        loaded = build_notes_map()
        os.makedirs(os.path.dirname(CACHE_JSON), exist_ok=True)
        try:
            with open(CACHE_JSON, "w", encoding="utf-8") as f:
                json.dump({"built_at": now, "map": loaded}, f, ensure_ascii=False)
        except Exception:
            pass

    _map_cache = loaded
    _map_loaded_at = now
    return loaded


def make_wikilink(item_key, title):
    """Return (wikilink_or_empty, kind).
    kind: 'obsidian' (合规双链) 或 'none'（库中无对应 Zotero 笔记，前端不显示该按钮）。
    """
    notes = get_notes_map()
    info = notes.get(item_key)
    if info and info.get("note_name"):
        alias = info.get("aliases") or ""
        if alias:
            return f"[[{info['note_name']}|{alias}]]", "obsidian"
        return f"[[{info['note_name']}]]", "obsidian"
    return "", "none"


def clean_wikilink_alias(wikilink, correct_abbr):
    """笔记 aliases 尾段（期刊缩写）可能继承自 Zotero 脏字段；展示层统一替换为校验过的简称。
    aliases 惯例格式为 '作者, 年份, 期刊缩写'（三段），只动第三段。"""
    if not wikilink or "|" not in wikilink or not correct_abbr:
        return wikilink
    mm = re.match(r"(\[\[[^\]|]+\|)([^\]]+)(\]\])", wikilink)
    if not mm:
        return wikilink
    parts = mm.group(2).split(",")
    if len(parts) >= 3:
        parts[-1] = " " + correct_abbr
        return mm.group(1) + ",".join(parts) + mm.group(3)
    return wikilink
