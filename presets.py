"""快捷预设 sidecar（画廊检索入口的人工维护清单）。

为什么独立文件而不是塞进 figures 表、也不写死在 HTML：
- 预置是人工资产，重抽/重跑批次不该动它（与 ratings.json 同一判断）；
- 写死在 HTML_CONTENT 里则每加一个词都要改 Python 源码再重启；
- 单人主机 + 多设备访问（overlay）下必须放服务端，否则各设备各一份。

存储格式：{"presets": [{"label": "...", "query": "..."}]}，原子写（临时文件 + os.replace）。
"""

import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_PATH = os.path.join(BASE_DIR, "presets.json")

MAX_PRESETS = 20
MAX_LABEL = 30
MAX_QUERY = 200

# 首次运行（无 presets.json）的种子，等同旧版写死在 HTML 里的四条
DEFAULT_PRESETS = [
    {"label": "全新世干湿与降水", "query": "Holocene moisture precipitation"},
    {"label": "青藏高原海拔增温", "query": "Tibetan Plateau elevation warming"},
    {"label": "湖泊有机碳埋藏", "query": "organic carbon burial lake"},
    {"label": "遥感植被动态", "query": "vegetation dynamics remote sensing"},
]

_LOCK = threading.Lock()
_state = {"mtime": None, "data": None}


def _clean(items):
    """校验并归一化。非法输入抛 ValueError（由 API 回 400），不静默丢弃。"""
    if not isinstance(items, list):
        raise TypeError("presets 必须是数组")
    if len(items) > MAX_PRESETS:
        raise ValueError(f"最多 {MAX_PRESETS} 条")
    cleaned = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise TypeError('每条形如 {"label": str, "query": str}')
        label = str(item.get("label") or "").strip()
        query = str(item.get("query") or "").strip()
        if not label:
            raise ValueError("显示名不能为空")
        if len(label) > MAX_LABEL:
            raise ValueError(f"显示名最长 {MAX_LABEL} 字：{label[:12]}")
        if len(query) > MAX_QUERY:
            raise ValueError(f"检索词最长 {MAX_QUERY} 字")
        if not query:
            query = label
        if label in seen:
            raise ValueError(f"显示名重复：{label}")
        seen.add(label)
        cleaned.append({"label": label, "query": query})
    return cleaned


def _read_file():
    try:
        with open(PRESETS_PATH, encoding="utf-8") as presets_file:
            raw = json.load(presets_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if isinstance(raw, dict):
        raw = raw.get("presets")
    try:
        return _clean(raw)
    except (ValueError, TypeError):
        return None


def load():
    """当前预设列表；文件缺失回种子（不落盘，首次保存才写）。文件被外部改动按 mtime 热重载。"""
    with _LOCK:
        try:
            mtime = os.path.getmtime(PRESETS_PATH)
        except OSError:
            mtime = None
        if _state["mtime"] != mtime or _state["data"] is None:
            loaded = _read_file() if mtime is not None else None
            _state["data"] = loaded if loaded is not None else [dict(p) for p in DEFAULT_PRESETS]
            _state["mtime"] = mtime
        return [dict(p) for p in _state["data"]]


def save(items):
    """整体替换（前端持有全量列表，避免逐条增删的并发叠加）。返回落盘后的列表。"""
    cleaned = _clean(items)
    with _LOCK:
        temp_path = PRESETS_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as presets_file:
            json.dump({"presets": cleaned}, presets_file, ensure_ascii=False, indent=2)
        os.replace(temp_path, PRESETS_PATH)
        _state["data"] = cleaned
        _state["mtime"] = os.path.getmtime(PRESETS_PATH)
    return [dict(p) for p in cleaned]
