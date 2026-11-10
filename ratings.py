"""个人评分 sidecar（0~5 星），独立于 figures 表存储。

为什么独立文件而不是 figures 表的一列：
reindex_families.py / reindex_all.py 走的是 `DELETE FROM figures WHERE item_key=?`
再重抽，算法升级时的全量重抽会让列里的评分一起归零。人工标注不可再生，
必须与可重抽的抽取结果物理分开。

键的归一化：fig_no 实测有 1024 种原始拼写（`Fig.1` / `Fig. 1` / `Fig.\n 1` /
`Fig.\xa0 1` / `FIG. 1` …），归一化（去空白与点号 + 小写）后仍有 795 种、其中
102 个键对应多种写法。所以键统一用 (item_key 大写, 归一化 fig_no)，重抽后
拼写变化不影响评分对得上，同篇因漂移留下的重复行也共享同一评分。

存储格式：{"KEY|fig1": 5, ...}，原子写（临时文件 + os.replace）。
"""

import json
import os
import re
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RATINGS_PATH = os.path.join(BASE_DIR, "ratings.json")

MIN_STARS = 1
MAX_STARS = 5

_LOCK = threading.Lock()
_state = {"mtime": None, "data": {}, "lookup": None}


def norm_fig(fig_no):
    """fig_no 归一化：抹掉空白（含 nbsp/narrow-nbsp）与点号，转小写。"""
    return re.sub(r"[\s.]", "", (fig_no or "").lower())


def make_key(item_key, fig_no):
    return f"{(item_key or '').strip().upper()}|{norm_fig(fig_no)}"


def _read_file():
    try:
        with open(RATINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        try:
            stars = int(v)
        except (TypeError, ValueError):
            continue
        if MIN_STARS <= stars <= MAX_STARS:
            out[k] = stars
    return out


def load():
    """返回当前评分字典；文件被外部改动时按 mtime 自动热重载。"""
    with _LOCK:
        try:
            mtime = os.path.getmtime(RATINGS_PATH)
        except OSError:
            mtime = None
        if mtime != _state["mtime"]:
            _state["data"] = _read_file() if mtime is not None else {}
            _state["mtime"] = mtime
            _state["lookup"] = None  # 文件变了，元组键副本失效
        return _state["data"]


def as_lookup():
    """转成 engine 过滤用的 {(item_key_upper, norm_fig): stars}，按 mtime 缓存。"""
    load()  # 顺带做热重载与失效标记
    if _state["lookup"] is None:
        lookup = {}
        for k, stars in _state["data"].items():
            item_key, _, fig = k.partition("|")
            lookup[(item_key, fig)] = stars
        _state["lookup"] = lookup
    return _state["lookup"]


def set_rating(item_key, fig_no, stars):
    """写一个评分。stars 为 0 或负数 = 清除该条。返回写入后的星级（清除返回 0）。"""
    if not (item_key or "").strip() or not norm_fig(fig_no):
        raise ValueError("item_key 与 fig_no 都不能为空")
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        raise ValueError("stars 必须是整数") from None
    key = make_key(item_key, fig_no)
    with _LOCK:
        # 注意：此处已持锁，必须直接调 _read_file()，不能再走 load()（Lock 不可重入会死锁）
        data = dict(_read_file())
        if MIN_STARS <= stars <= MAX_STARS:
            data[key] = stars
        else:
            data.pop(key, None)
        tmp = RATINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, RATINGS_PATH)
        _state["data"] = data
        _state["mtime"] = os.path.getmtime(RATINGS_PATH)
        _state["lookup"] = None
    return data.get(key, 0)


def summarize():
    """给 /api/stats 用：已评分条数与分布。"""
    data = load()
    dist = {str(n): 0 for n in range(MIN_STARS, MAX_STARS + 1)}
    for stars in data.values():
        dist[str(stars)] = dist.get(str(stars), 0) + 1
    return {"rated": len(data), "distribution": dist}
