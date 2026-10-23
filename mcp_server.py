"""
zotero-figure MCP Server
Exposes Zotero GeoFigure semantic search and visual figure inspection via standard Model Context Protocol (FastMCP).
Supports both local stdio transport and remote streamable-http transport.
"""

import argparse
import io
import json
import os
import sys

from PIL import Image as PILImage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import IMAGE_DIR, FigureDB, FigureSearcher
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image as MCPImage

mcp = FastMCP(
    name="zotero-figure",
    instructions="Zotero 地学文献图表语义检索与多模态视觉直读服务。支持按关键词、区域、指标或文献 KEY 检索核心剖面图与年代学曲线，直接返回多模态图像流与图注元数据。",
    host=os.environ.get("GEO_FIGURE_HOST", "100.64.0.10"),
    port=23122,
)

searcher = None
db = FigureDB()


def get_searcher() -> FigureSearcher:
    global searcher
    if searcher is None:
        searcher = FigureSearcher()
    return searcher


def _parent_of(hit):
    """整图行=自身 fig_no；面板行=panels_json.parent_fig（同父多面板合并用）。"""
    if hit.get("origin") == "panel" and hit.get("panels_json"):
        try:
            return json.loads(hit["panels_json"]).get("parent_fig") or hit.get("fig_no", "")
        except Exception:
            pass
    return hit.get("fig_no", "")


def _group_by_parent(hits):
    """按 (item_key, parent) 归并，保序；同父多面板占一个槽位（工单§二.5）。"""
    groups, index = [], {}
    for h in hits:
        k = (h.get("item_key", ""), _parent_of(h))
        if k not in index:
            index[k] = len(groups)
            groups.append([])
        groups[index[k]].append(h)
    return groups


# ---- 面板定向取图（WORKORDER_panel_mcp_return 2026-10-19）----
# 默认路径零改动：不传 panel 仍走 MCPImage(path=原文件)。
# 面板优先用已抽好的面板行文件（原生像素）；upscale_to 只"补到目标"绝不超原生；
# 单张 ≤2MB 超限降 q60；面板缺失回退整图并在 text 明示。
VIEW_MAX_SIDE = 1280
IMG_BYTE_CAP = 2 * 1024 * 1024


def _resolve_panel_path(item_key, parent_fig, letter):
    """取同篇同父的指定面板行文件。返回 (path, w, h) 或 None。"""
    if not item_key or not parent_fig:
        return None
    s = get_searcher()
    want = f"{parent_fig}{letter}".replace(" ", "").lower()
    for h in s.search(query="", item_key=item_key, top_k=400, origin="panel"):
        fn = (h.get("fig_no") or "").replace(" ", "").lower()
        if fn == want:
            p = h.get("image_path") or ""
            if p and os.path.exists(p):
                try:
                    with PILImage.open(p) as im:
                        return p, im.width, im.height
                except Exception:
                    return p, 0, 0
    return None

def _available_panels(item_key, parent_fig):
    """该父图已收录的面板字母。"""
    s = get_searcher()
    pf = (parent_fig or "").replace(" ", "").lower()
    letters = []
    for h in s.search(query="", item_key=item_key, top_k=400, origin="panel"):
        fn = (h.get("fig_no") or "").replace(" ", "").lower()
        if fn.startswith(pf) and len(fn) == len(pf) + 1 and fn[-1].isalpha():
            letters.append(fn[-1])
    return sorted(set(letters))

def _encode_capped(im, quality=88):
    """编码并保证 ≤2MB：先 q88，超限降 q60，仍超则等比缩（工单§三.3）。返回 (bytes, q, note)。"""
    for q in (quality, 60):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if len(buf.getvalue()) <= IMG_BYTE_CAP:
            return buf.getvalue(), q, ""
    scale = (IMG_BYTE_CAP / float(len(buf.getvalue()))) ** 0.5
    small = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                      PILImage.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=60, optimize=True)
    return buf.getvalue(), 60, f"超2MB已缩至{small.width}x{small.height}"

def _panel_payload(item_key, parent_fig, letter, max_side=1600, crop_mode="native"):
    """构建面板图像流。返回 (text, MCPImage|None)；面板缺失时 text 说明、image 为 None。"""
    hit = _resolve_panel_path(item_key, parent_fig, letter)
    if hit is None:
        avail = _available_panels(item_key, parent_fig)
        tail = (f"（该图已收录面板: {','.join(avail)}）" if avail else "（该图无面板行）")
        return f"panel={letter} 未收录，已返回整图{tail}", None
    path, nw, nh = hit
    if not nw:
        return f"panel={letter} 文件不可读，已返回整图", None
    try:
        im = PILImage.open(path).convert("RGB")
    except Exception as e:
        return f"panel={letter} 读取失败（{e}），已返回整图", None

    native_long = max(nw, nh)
    # native: 不超查看端上限且绝不放大；upscale_to: 补/缩到 min(max_side, 原生自然上限)
    if crop_mode == "upscale_to":
        target = min(max_side, native_long) if native_long < max_side else min(VIEW_MAX_SIDE, native_long)
    else:
        target = min(VIEW_MAX_SIDE, native_long)
    rendered_long = target
    if rendered_long != native_long:
        k = rendered_long / float(native_long)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                       PILImage.LANCZOS)
    data, q, note = _encode_capped(im)

    # gain 口径（可判定）：本次交付长边 ÷ "整图入模时该面板实得长边"。
    # 整图入模时父图被压到 ≤1280，面板只占 pt 比例 share → 实得 = 1280 × share。
    share = _panel_share(item_key, parent_fig, letter)
    if share:
        today = VIEW_MAX_SIDE * share
        gain = rendered_long / today if today > 0 else 1.0
        gain_s = f"{gain:.2f} (整图实得≈{today:.0f}px)"
    else:
        gain_s = "n/a(无父图bpb数据)"
    text = (f"panel={letter} native={nw}x{nh} returned={im.width}x{im.height} "
            f"gain={gain_s} mode={crop_mode} q={q}")
    if note:
        text += f" | {note}"
    return text, MCPImage(data=data, format="jpeg")


def _panel_share(item_key, parent_fig, letter):
    """面板 pt 长边 ÷ 父图 region pt 长边（用于 gain 换算）；无数据返回 None。"""
    s = get_searcher()
    pf = (parent_fig or "").replace(" ", "").lower()
    want = f"{pf}{letter}"
    for h in s.search(query="", item_key=item_key, top_k=400, origin="panel"):
        fn = (h.get("fig_no") or "").replace(" ", "").lower()
        if fn != want:
            continue
        try:
            d = json.loads(h.get("panels_json") or "{}")
            bb = d.get("bbox_pt")
            if not bb:
                return None
            panel_long = max(bb[2] - bb[0], bb[3] - bb[1])
            # 父图 region：取该父图整图行同页的近似——用 panels_json 里的 parent_bbox（若无则用页面宽）
            pb = d.get("parent_pt")
            if pb:
                parent_long = max(pb[2] - pb[0], pb[3] - pb[1])
            else:
                return None
            return panel_long / parent_long if parent_long > 0 else None
        except Exception:
            return None
    return None


def _resolve_whole_path(item_key, parent_fig):
    """取该父图的整图行文件（回退用）。"""
    s = get_searcher()
    pf = (parent_fig or "").replace(" ", "").lower()
    for h in s.search(query="", item_key=item_key, top_k=400, origin="whole"):
        fn = (h.get("fig_no") or "").replace(" ", "").lower()
        if fn == pf:
            p = h.get("image_path") or ""
            return p if p and os.path.exists(p) else None
    return None


@mcp.tool()
def search_figures(
    query: str,
    item_key: str = "",
    top_k: int = 3,
    return_image: bool = True,
    with_panels: bool = True,
    panel: str = "",
    panel_pick: str = "",
    crop_mode: str = "native",
    author: str = "",
    journal: str = "",
    journal_exact: bool = False,
    year_min: int = 0,
    year_max: int = 0,
) -> list:
    """
    检索地学文献图表。支持语义与关键词检索，直接返回图注元数据及图像流。

    参数:
    - query: 检索词（如 'Altai pollen Holocene', 'Bosten lake level age model'）
    - item_key: 可选的文献 KEY（如 '5L2UE86C' 或 'KEY-5L2UE86C'），限定在单篇文献内检索
    - top_k: 返回图表数量（1-10，默认 3；同父多面板合并计一个槽位）
    - return_image: 是否内嵌图像流（默认 True，最多 3 张）
    - with_panels: 是否透传子面板行（默认 True）；False 只回整图行（旧行为）
    - panel: 只取指定面板字母（如 'a'、'b'）。命中父图后返回该面板本体，
             1280 查看预算全部花在单面板上（判读曲线/数值细节时用）。
             **不传则行为与以前逐字节一致**。
    - panel_pick: 'first' 取该图第一个面板；与 panel 二选一，panel 优先。
    - crop_mode: 'native'（默认，不超过查看端 1280 上限且绝不放大）
                 / 'upscale_to'（补到 max_side，但不超过原生物理分辨率）。
    - author: 作者过滤（中文/拼音/英文均可，如 '唐丽雅' 或 'Tang'，模糊匹配拼音变体）；
              与 query 正交叠加：先按作者筛，再按语义排序。
    - journal: 期刊过滤（默认子串匹配；journal_exact=True 时精确相等）。
    - year_min / year_max: 年份范围过滤（0 表示不限）。
    """
    s = get_searcher()
    top_k = max(1, min(10, top_k))
    clean_key = item_key.replace("KEY-", "").strip() if item_key else None
    # 面板行独占 1280 预算 → 排序时优先取面板，整图同父则合并展示
    hits = s.search(query=query, item_key=clean_key, top_k=top_k * 4,
                   origin=None if with_panels else "whole",
                   author=author or None, journal_filter=journal or None,
                   journal_exact=journal_exact,
                   year_min=year_min or None, year_max=year_max or None)

    if not hits:
        msg = f"未找到匹配的图表（query='{query}', item_key='{item_key}'）。"
        return [msg]

    groups = _group_by_parent(hits)[:top_k]

    # ---- 面板定向模式：只回指定面板本体 + 元信息（默认不传 panel 时此段整体跳过）----
    want_panel = (panel or "").strip().lower()[:1]
    if not want_panel and (panel_pick or "").strip().lower() == "first":
        first = groups[0] if groups else []
        ps = [h for h in first if h.get("origin") == "panel"]
        if ps:
            want_panel = (ps[0].get("fig_no") or "")[-1:].lower()

    if want_panel:
        grp = groups[0] if groups else []
        if not grp:
            return [f"未找到匹配的图表（query='{query}', item_key='{item_key}'）。"]
        h0 = grp[0]
        ik = h0.get("item_key", "")
        parent = _parent_of(h0)
        yr, author = h0.get("year", ""), h0.get("authors", "")
        journal = h0.get("journal_abbr") or h0.get("journal", "")
        head = [f"锁定面板：{ik} — {parent}{want_panel}"
                f"（{author} {yr}, {journal}）"]
        note, img = _panel_payload(ik, parent, want_panel, crop_mode=crop_mode)
        head.append("    " + note)
        if img is None:
            # 回退：必须是父图整图行，不能是命中的面板行（工单§三.4 不静默）
            whole = _resolve_whole_path(ik, parent)
            if whole:
                head.append(f"    回退整图: {os.path.basename(whole)}")
                return ["\n".join(head), MCPImage(path=whole)] if return_image else ["\n".join(head)]
            return ["\n".join(head)]
        return ["\n".join(head), img] if return_image else ["\n".join(head)]

    lines = [f"找到 {sum(len(g) for g in groups)} 张相关图表（{len(groups)} 个图号）：\n"]
    image_paths = []

    for i, grp in enumerate(groups, 1):
        h0 = grp[0]
        ik = h0.get("item_key", "")
        parent = _parent_of(h0)
        yr = h0.get("year", "")
        author = h0.get("authors", "")
        journal = h0.get("journal_abbr") or h0.get("journal", "")
        score = max(h.get("score", 0.0) for h in grp)
        panels = [h for h in grp if h.get("origin") == "panel"]
        tag = f"（含 {len(panels)} 个面板）" if panels else ""
        lines.append(f"[{i}] {author} ({yr}, {journal}) — {parent} [KEY: {ik}]{tag}")
        lines.append(f"    得分: {score:.3f}")
        for h in grp:
            is_panel = h.get("origin") == "panel"
            label = h.get("fig_no", "Figure")
            cap = h.get("caption", "").strip()
            lines.append(f"    - {label}: {cap}")
            lines.append(f"      路径: {h.get('image_path', '')}")
        lines.append("")
        # 图像流：有面板优先给面板（原生分辨率），否则给整图
        picks = panels if panels else [h0]
        for h in picks:
            p = h.get("image_path", "")
            if p and os.path.exists(p) and p not in image_paths:
                image_paths.append(p)

    results = ["\n".join(lines)]

    if return_image:
        for p in image_paths[:3]:
            try:
                results.append(MCPImage(path=p))
            except Exception as e:
                results.append(f"[注意：图像流封装失败 {os.path.basename(p)}: {e}]")

    return results


@mcp.tool()
def get_figure_image(filename_or_path: str, panel: str = "", crop_mode: str = "native") -> list:
    """
    通过文件名或完整路径直接读取单张图表的多模态图像流。

    参数:
    - filename_or_path: 图表文件名（如 '5L2UE86C_Figure_4_p7.webp'）或完整物理路径
    - panel: 面板字母（如 'a'）。传父图文件名 + 面板字母 → 服务端取该面板本体
             （用已抽好的面板文件；若无则按 panels_json 从父图裁）。不传则原样返回文件。
    - crop_mode: 'native'（默认，≤查看端上限且不放大）/ 'upscale_to'（补到 1600，不超原生）
    """
    target = filename_or_path.strip().strip('"').strip("'")
    if not os.path.isabs(target):
        target = os.path.join(IMAGE_DIR, target)

    want = (panel or "").strip().lower()[:1]

    # 面板模式：先从文件名反解 item_key 与父图号，再取面板行
    if want:
        base = os.path.basename(target)
        m = __import__("re").match(r"^([A-Z0-9]{8})_(.+?)(?:_p\d+)?\.webp$", base, __import__("re").I)
        if not m:
            return [f"无法从文件名解析 item_key：{base}"]
        ik = m.group(1)
        import re as _re
        # 文件名 slug "Fig__4" → "Fig. 4"：下划线序列先归一为单空格，再补 "Fig"/"Figure" 后的点
        parent = _re.sub(r"_+", " ", m.group(2)).strip()
        parent = _re.sub(r"^(Fig|Figure)\s+(?=S?\d)", lambda mm: f"{mm.group(1)}. ", parent)
        parent = _re.sub(r"\s+", " ", parent)
        note, img = _panel_payload(ik, parent, want, crop_mode=crop_mode)
        head = [f"请求 {base} 的 panel={want}（解析: item_key={ik}, 父图={parent}）", "    " + note]
        if img is None:
            # 回退父图整图：优先用同名整图行，其次才用传入文件
            whole = _resolve_whole_path(ik, parent) or (target if os.path.exists(target) else None)
            if whole and os.path.exists(whole):
                head.append("    回退整图: " + os.path.basename(whole))
                return ["\n".join(head), MCPImage(path=whole)]
            return ["\n".join(head)]
        return ["\n".join(head), img]

    if not os.path.exists(target):
        return [f"错误：图表文件不存在：{target}"]

    fname = os.path.basename(target)
    return [f"成功读取图表: {fname}", MCPImage(path=target)]


@mcp.tool()
def list_paper_figures(item_key: str) -> str:
    """
    列出指定文献包含的全部图表编号与图注清单。

    参数:
    - item_key: 文献 KEY（如 '5L2UE86C' 或 'KEY-5L2UE86C'）
    """
    clean_key = item_key.replace("KEY-", "").strip()
    s = get_searcher()
    hits = s.search(query="", item_key=clean_key, top_k=200)

    if not hits:
        return f"未找到文献 {clean_key} 的图表记录。"

    lines = [f"文献 {clean_key} 共收录 {len(hits)} 条图录（整图+面板）：\n"]
    for i, h in enumerate(hits, 1):
        fno = h.get("fig_no", "Figure")
        page = h.get("page_no", "")
        caption = h.get("caption", "").strip()
        fname = os.path.basename(h.get("image_path", ""))
        mark = "  ⟦面板⟧" if h.get("origin") == "panel" else ""
        lines.append(f"{i}. {fno} (第 {page} 页) [{fname}]{mark}")
        lines.append(f"   图注: {caption}\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="zotero-figure MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="streamable-http",
        help="MCP 传输协议（默认 streamable-http）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=23122,
        help="HTTP 监听端口（默认 23122）",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("GEO_FIGURE_HOST", "100.64.0.10"),
        help="HTTP 监听地址（默认 100.64.0.10）",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()