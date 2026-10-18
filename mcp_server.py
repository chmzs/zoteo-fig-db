"""
zotero-figure MCP Server
Exposes Zotero GeoFigure semantic search and visual figure inspection via standard Model Context Protocol (FastMCP).
Supports both local stdio transport and remote streamable-http transport.
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import IMAGE_DIR, FigureDB, FigureSearcher
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image as MCPImage

mcp = FastMCP(
    name="zotero-figure",
    instructions="Zotero 地学文献图表语义检索与多模态视觉直读服务。支持按关键词、区域、指标或文献 KEY 检索核心剖面图与年代学曲线，直接返回多模态图像流与图注元数据。",
    host="0.0.0.0",
    port=23122,
)

searcher = None
db = FigureDB()


def get_searcher() -> FigureSearcher:
    global searcher
    if searcher is None:
        searcher = FigureSearcher()
    return searcher


@mcp.tool()
def search_figures(
    query: str,
    item_key: str = "",
    top_k: int = 3,
    return_image: bool = True,
) -> list:
    """
    检索地学文献图表。支持语义与关键词检索，直接返回图注元数据及第一张图的多模态图像流。

    参数:
    - query: 检索词（如 'Altai pollen Holocene', 'Bosten lake level age model'）
    - item_key: 可选的文献 KEY（如 '5L2UE86C'），限定在单篇文献内检索
    - top_k: 返回图表数量（1-10，默认 3）
    - return_image: 是否在返回结果中直接内嵌首张图表的图像流（默认 True）
    """
    s = get_searcher()
    top_k = max(1, min(10, top_k))
    clean_key = item_key.replace("KEY-", "").strip() if item_key else None
    hits = s.search(query=query, item_key=clean_key, top_k=top_k)

    if not hits:
        msg = f"未找到匹配的图表（query='{query}', item_key='{item_key}'）。"
        return [msg]

    lines = [f"找到 {len(hits)} 张相关图表：\n"]
    first_image_path = None

    for i, h in enumerate(hits, 1):
        ik = h.get("item_key", "")
        fno = h.get("fig_no", "Figure")
        yr = h.get("year", "")
        author = h.get("authors", "")
        journal = h.get("journal_abbr") or h.get("journal", "")
        caption = h.get("caption", "").strip()
        img_path = h.get("image_path", "")
        score = h.get("score", 0.0)

        lines.append(f"[{i}] {author} ({yr}, {journal}) — {fno} [KEY: {ik}]")
        lines.append(f"    得分: {score:.3f}")
        lines.append(f"    图注: {caption}")
        lines.append(f"    本地路径: {img_path}\n")

        if i == 1 and img_path and os.path.exists(img_path):
            first_image_path = img_path

    results = ["\n".join(lines)]

    if return_image and first_image_path:
        try:
            results.append(MCPImage(path=first_image_path))
        except Exception as e:
            results.append(f"[注意：首图图像流封装失败: {e}]")

    return results


@mcp.tool()
def get_figure_image(filename_or_path: str) -> list:
    """
    通过文件名或完整路径直接读取单张图表的多模态图像流。

    参数:
    - filename_or_path: 图表文件名（如 '5L2UE86C_Figure_4_p7.webp'）或完整物理路径
    """
    target = filename_or_path.strip().strip('"').strip("'")
    if not os.path.isabs(target):
        target = os.path.join(IMAGE_DIR, target)

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
    hits = s.search(query="", item_key=clean_key, top_k=50)

    if not hits:
        return f"未找到文献 {clean_key} 的图表记录。"

    lines = [f"文献 {clean_key} 共收录 {len(hits)} 张图表：\n"]
    for i, h in enumerate(hits, 1):
        fno = h.get("fig_no", "Figure")
        page = h.get("page_no", "")
        caption = h.get("caption", "").strip()
        fname = os.path.basename(h.get("image_path", ""))
        lines.append(f"{i}. {fno} (第 {page} 页) [{fname}]")
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
        default="0.0.0.0",
        help="HTTP 监听地址（默认 0.0.0.0）",
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
