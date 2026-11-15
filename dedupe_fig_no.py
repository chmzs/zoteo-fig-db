"""同篇同图去重：fig_no 拼写漂移（Figure 1 / FIGURE 1 / Fig.1）留下的重复行。

判据：同 (item_key, norm_fig) 且行数 >1。norm_fig = 去空白去点号转小写（与 ratings 键同口径，
所以删行不影响评分——评分键本来就按 norm_fig 存）。

保留者优先级：
  1. 题注不是"正文句式"（不像 "Figure 1 shows…"）
  2. 题注更长（信息更全）
  3. 图片面积更大
  4. 页码更小

用法：python dedupe_fig_no.py [--apply]   默认只打印计划（dry-run）
"""

import argparse
import os
import re
import sqlite3

from PIL import Image

from engine import DB_PATH

BODY_STYLE = re.compile(
    r"^(?:Fig(?:ure)?\.?)\s*\d+[a-z]?\s+"
    r"(shows|show|presents|present|illustrates|illustrate|displays|display|depicts|depict|indicates|indicate)",
    re.I)


def norm_fig(fig_no):
    return re.sub(r"[\s.]", "", (fig_no or "").lower())


def area_of(path):
    try:
        with Image.open(path) as im:
            return im.size[0] * im.size[1]
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正删除（默认 dry-run）")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=60)
    rows = conn.execute(
        "SELECT id, item_key, fig_no, COALESCE(caption,''), image_path, page_no FROM figures"
        " ORDER BY item_key, page_no").fetchall()

    # 只把"页码相邻（差<=2）"的行视为同一张图：教材/报告按章编号时，
    # 不同章节的 "Figure 2" 是两张不同的图（实测 9EXZZYYV p9 与 p62）。
    groups = {}
    for row in rows:
        groups.setdefault((row[1], norm_fig(row[2])), []).append(row)

    clustered = {}
    for key, members in groups.items():
        members.sort(key=lambda r: r[5] or 0)
        cluster = []
        for row in members:
            if cluster and (row[5] or 0) - (cluster[-1][5] or 0) > 2:
                if len(cluster) > 1:
                    clustered[(key[0], key[1], cluster[0][5])] = list(cluster)
                cluster = []
            cluster.append(row)
        if len(cluster) > 1:
            clustered[(key[0], key[1], cluster[0][5])] = cluster
    groups = clustered

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    total_extra = sum(len(v) - 1 for v in dup_groups.values())
    print(f"重复组={len(dup_groups)}  冗余行={total_extra}")

    removed = 0
    freed = 0
    for (item_key, norm, _page), members in sorted(dup_groups.items(), key=lambda kv: -len(kv[1]))[:12]:
        ranked = sorted(members, key=lambda r: (
            bool(BODY_STYLE.match(r[3])),          # 正文句式排后
            -len(r[3]),                            # 题注长的优先
            -area_of(r[4] or ""),                  # 图大的优先
            r[5] or 0))                            # 页码小的优先
        keep = ranked[0]
        print(f"  {item_key} norm={norm}: {len(members)} 行 -> 保留 {keep[2]!r} (p{keep[5]}, cap={len(keep[3])})")

    if not args.apply:
        print("\ndry-run：未删除。确认后加 --apply。")
        conn.close()
        return

    for (_item_key, _norm, _page), members in dup_groups.items():
        ranked = sorted(members, key=lambda r: (
            bool(BODY_STYLE.match(r[3])), -len(r[3]), -area_of(r[4] or ""), r[5] or 0))
        keep = ranked[0]
        for row in ranked[1:]:
            row_id, _key, _fig, _cap, path, _page = row
            try:
                conn.execute("DELETE FROM fts_figures WHERE rowid=?", (row_id,))
            except sqlite3.OperationalError:
                pass
            conn.execute("DELETE FROM figures WHERE id=?", (row_id,))
            removed += 1
            for candidate in (path, (path or "")[:-5] + ".thumb.webp"):
                if candidate and os.path.exists(candidate):
                    freed += os.path.getsize(candidate)
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass
    conn.commit()
    conn.close()
    print(f"\n已删除 {removed} 行，释放 {freed/1048576:.1f} MB")


if __name__ == "__main__":
    main()
