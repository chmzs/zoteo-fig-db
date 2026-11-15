"""
Notes Map: item_key -> Obsidian Zotero 笔记双链 (确定性扫描)
文件名规则: <year>_<作者>_<标题截断>_KEY-<itemKey>.md
别名: frontmatter 的 aliases 行 (如 'Grinnell, 1917, Auk')
映射不到笔记时退化为 zotero://select 的 markdown 链接
"""

import json
import os

import config as app_config
import re
import time

NOTES_DIR = app_config.notes_dir()   # 配置页设定；留空则该功能静默跳过
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
            # 缓存必须绑定构建时目录：配置页改了 notes_dir 后旧缓存会静默失效
            # （2026-11-15 实测：用错误目录建了 2 条缓存，按钮整片消失且 24h 内不复原）
            same_dir = (os.path.normcase(os.path.normpath(cached.get("notes_dir") or ""))
                        == os.path.normcase(os.path.normpath(NOTES_DIR)))
            if same_dir and (now - cached.get("built_at", 0)) < 86400:  # daily refresh
                loaded = cached.get("map", {})
        except Exception:
            loaded = None

    if loaded is None:
        loaded = build_notes_map()
        os.makedirs(os.path.dirname(CACHE_JSON), exist_ok=True)
        try:
            with open(CACHE_JSON, "w", encoding="utf-8") as f:
                json.dump({"built_at": now, "notes_dir": NOTES_DIR, "map": loaded},
                          f, ensure_ascii=False)
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


def obsidian_uri(item_key):
    '''obsidian://open 链接：一键在 Obsidian 打开该文献笔记；无笔记返回空串。

    file= 必须是 vault 相对路径（不含 .md），vault= 是 vault 目录名。
    '''
    info = get_notes_map().get(item_key)
    if not info or not info.get("note_name"):
        return ""
    from urllib.parse import quote

    note_name = info["note_name"]
    rel = note_name
    root = app_config.vault_root()
    if root:
        try:
            rel = os.path.relpath(os.path.join(NOTES_DIR, note_name + ".md"), root)
        except ValueError:
            rel = note_name
    rel = rel.replace("\\", "/")
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return f"obsidian://open?vault={quote(app_config.obsidian_vault())}&file={quote(rel)}"
