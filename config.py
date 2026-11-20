"""运行期配置：Zotero 数据/附件目录、Obsidian 笔记目录、服务端口。

取值优先级：环境变量 > config.json > 自动检测 > 默认值。

为什么要有自动检测：每个人的 Zotero 位置不同（默认 ~/Zotero，也可能自建目录），
而且 Zotero 自己把选择写进了 profile 的 prefs.js——读它比猜目录可靠。
配置页（/config）负责展示检测结果并允许覆盖。
"""

import glob
import json
import os
import re
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

ENV_MAP = {
    "zotero_dir": "GEO_ZOTERO_DIR",
    "storage_dir": "GEO_ZOTERO_STORAGE",
    "notes_dir": "GEO_NOTES_DIR",
    "port": "GEO_FIGURE_PORT",
}

DEFAULTS = {
    "zotero_dir": "",
    "storage_dir": "",
    "notes_dir": "",
    "port": 5173,
}


def _read_pref(pref_file, key):
    try:
        with open(pref_file, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r'user_pref\("%s",\s*"([^"]*)"\)' % re.escape(key), text)
    return match.group(1) if match else None


def _profile_pref_files():
    home = os.path.expanduser("~")
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), "Zotero", "Zotero", "Profiles"),
        os.path.join(home, ".zotero", "zotero"),
        os.path.join(home, "Library", "Application Support", "Zotero", "Profiles"),
    ]
    files = []
    for root in roots:
        if root and os.path.isdir(root):
            files.extend(glob.glob(os.path.join(root, "*", "prefs.js")))
    return files


def _looks_like_zotero(path):
    return bool(path) and os.path.isfile(os.path.join(path, "zotero.sqlite"))


def detect_zotero_dir():
    """按 Zotero 自己的记录推断数据目录，返回 (path, source)。"""
    home = os.path.expanduser("~")
    for pref_file in _profile_pref_files():
        data_dir = _read_pref(pref_file, "extensions.zotero.dataDir")
        if data_dir and _looks_like_zotero(data_dir):
            return data_dir, "prefs.js dataDir"
        last_dir = _read_pref(pref_file, "extensions.zotero.lastDataDir")
        if last_dir:
            candidate = last_dir if os.path.isabs(last_dir) else os.path.join(home, last_dir)
            if _looks_like_zotero(candidate):
                return candidate, "prefs.js lastDataDir"
    default = os.path.join(home, "Zotero")
    return default, "默认 ~/Zotero" if _looks_like_zotero(default) else "默认 ~/Zotero（未找到 zotero.sqlite）"


def _read_file():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


_CACHE = {"stamp": None, "values": None}


def _config_stamp():
    """config.json 的 (mtime, size)；文件不存在时为 None。"""
    try:
        info = os.stat(CONFIG_PATH)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def invalidate():
    """清配置缓存（保存后或改了环境变量时调）。"""
    _CACHE["stamp"] = None
    _CACHE["values"] = None


def load():
    """合并后的有效配置（含来源标注）。

    结果按 config.json 的 (mtime, size) 缓存：自动检测要读 Zotero 的 prefs.js，
    每次调用都重读会把检索路径拖死（实测 100 条结果 = 400 次文件读、1.1 秒）。
    """
    stamp = _config_stamp()
    if _CACHE["values"] is not None and _CACHE["stamp"] == stamp:
        return _CACHE["values"]

    stored = _read_file()
    zotero_dir, source = detect_zotero_dir()
    values = dict(DEFAULTS)
    if zotero_dir:
        values["zotero_dir"] = zotero_dir
        values["storage_dir"] = os.path.join(zotero_dir, "storage")
    if stored.get("zotero_dir"):
        values["zotero_dir"] = stored["zotero_dir"]
        values["storage_dir"] = stored.get("storage_dir") or os.path.join(stored["zotero_dir"], "storage")
    if stored.get("storage_dir"):
        values["storage_dir"] = stored["storage_dir"]
    if stored.get("notes_dir"):
        values["notes_dir"] = stored["notes_dir"]
    if stored.get("port"):
        values["port"] = stored["port"]

    for key, env_name in ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw:
            values[key] = int(raw) if key == "port" else raw

    values["_sources"] = {
        "zotero_dir": "环境变量" if os.environ.get(ENV_MAP["zotero_dir"]) else (
            "config.json" if stored.get("zotero_dir") else source),
        "storage_dir": "环境变量" if os.environ.get(ENV_MAP["storage_dir"]) else (
            "config.json" if stored.get("storage_dir") else "由 zotero_dir 推导"),
        "notes_dir": "环境变量" if os.environ.get(ENV_MAP["notes_dir"]) else (
            "config.json" if stored.get("notes_dir") else "未配置"),
        "port": "环境变量" if os.environ.get(ENV_MAP["port"]) else (
            "config.json" if stored.get("port") else "默认值"),
    }
    _CACHE["stamp"] = stamp
    _CACHE["values"] = values
    return values


def validate(payload):
    """字段级校验；返回 (cleaned, errors)。只校验明确给出的字段。"""
    cleaned, errors = {}, {}
    zotero_dir = (payload.get("zotero_dir") or "").strip()
    if zotero_dir:
        if not os.path.isdir(zotero_dir):
            errors["zotero_dir"] = "目录不存在"
        elif not _looks_like_zotero(zotero_dir):
            errors["zotero_dir"] = "目录里没有 zotero.sqlite"
        else:
            cleaned["zotero_dir"] = zotero_dir
    storage_dir = (payload.get("storage_dir") or "").strip()
    if storage_dir:
        if not os.path.isdir(storage_dir):
            errors["storage_dir"] = "目录不存在"
        else:
            cleaned["storage_dir"] = storage_dir
    notes_dir = (payload.get("notes_dir") or "").strip()
    if notes_dir and not os.path.isdir(notes_dir):
        errors["notes_dir"] = "目录不存在（可以留空）"
    elif notes_dir:
        cleaned["notes_dir"] = notes_dir
    port = payload.get("port")
    if port not in (None, ""):
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            errors["port"] = "必须是整数"
        else:
            if not (1024 <= port_int <= 65535):
                errors["port"] = "端口需在 1024-65535"
            else:
                cleaned["port"] = port_int
    return cleaned, errors


def save(payload):
    """原子写入 config.json；返回 (cleaned, errors)。"""
    cleaned, errors = validate(payload)
    if errors:
        return cleaned, errors
    data = _read_file()
    data.update(cleaned)
    temp_path = CONFIG_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, CONFIG_PATH)
    return _read_file(), {}


def zotero_dir():
    return load()["zotero_dir"]


def storage_dir():
    return load()["storage_dir"]


def notes_dir():
    return load()["notes_dir"]


def port():
    return int(load()["port"])


def vault_root():
    '''从 notes_dir 向上找含 .obsidian 的目录 = Obsidian vault 根；找不到返回空串。'''
    path = notes_dir()
    while path and len(path) > 3:
        if os.path.isdir(os.path.join(path, ".obsidian")):
            return path
        parent = os.path.dirname(path.rstrip("\\/"))
        if parent == path:
            break
        path = parent
    return ""


def obsidian_vault():
    '''vault 名称（obsidian://open?vault=<name> 用）。'''
    root = vault_root()
    return os.path.basename(root) if root else ""
