"""元数据回填：按 Zotero 现值刷新 figures 表的 title / year / journal /
journal_abbr / authors / authors_norm，不碰 PDF、不碰 embedding、不碰 fig_no。

为什么需要这一步：
1. 刊名原先只查 publicationTitle，而书籍/学位论文/会议论文的"刊名"实际存在
   publisher / university / bookTitle / proceedingsTitle → 136 篇恒空。
2. 作者原先只查 creatorType='author'，书籍的 editor、软件的 programmer 取不到
   → 15 篇恒空（其中 author 类型为 0 篇）。
3. 用户在 Zotero 手工补录的年份与作者需要同步进库。

只改元数据列，不重新抽取图像。写入后 bump indexed_at，engine 的缓存签名
(count, MAX(indexed_at), MAX(id)) 随之变化，服务重启即自动重建内存缓存。

用法：
  python backfill_meta.py --dry-run   # 只报告将变更的行数与样本
  python backfill_meta.py             # 实际写入
"""

import argparse
import os
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import DB_PATH
from indexer import get_zotero_meta_map

FIELDS = ("title", "year", "journal", "journal_abbr", "authors", "authors_norm")


def _norm(field, value):
    return int(value or 0) if field == "year" else (value or "")


def _diff_missing(row, new):
    """保守模式：只填空，不动既有值。

    journal_abbr 只在 journal 原本为空时跟着补——否则 resolve_abbr 会按
    "Zotero 原值优先" 把已经美化的 "Ecol. Monogr." 退回 "ECOL MONOGR"
    （2026-11-10 dry-run 实测 406 行这类退化）。
    """
    diff = {}
    old_journal = _norm("journal", row[3])
    new_journal = _norm("journal", new.get("journal"))

    if not old_journal and new_journal:
        diff["journal"] = (old_journal, new_journal)
        new_abbr = _norm("journal_abbr", new.get("journal_abbr"))
        if new_abbr and new_abbr != _norm("journal_abbr", row[4]):
            diff["journal_abbr"] = (_norm("journal_abbr", row[4]), new_abbr)

    old_year = _norm("year", row[2])
    new_year = _norm("year", new.get("year"))
    if not old_year and new_year:
        diff["year"] = (old_year, new_year)

    old_authors = _norm("authors", row[5])
    new_authors = _norm("authors", new.get("authors"))
    if not old_authors and new_authors:
        diff["authors"] = (old_authors, new_authors)
        diff["authors_norm"] = (_norm("authors_norm", row[6]),
                                _norm("authors_norm", new.get("authors_norm")))

    old_title = _norm("title", row[1])
    new_title = _norm("title", new.get("title"))
    if not old_title and new_title:
        diff["title"] = (old_title, new_title)
    return diff


def _diff_overwrite(row, new):
    """覆盖模式：以 Zotero 为准全字段重写（含已美化的缩写回退风险）。"""
    diff = {}
    for idx, field in enumerate(FIELDS, start=1):
        old_val = _norm(field, row[idx])
        new_val = _norm(field, new.get(field))
        if old_val != new_val:
            diff[field] = (old_val, new_val)
    return diff


def main():
    parser = argparse.ArgumentParser(description="按 Zotero 现值回填 figures 元数据")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写库")
    parser.add_argument("--overwrite", action="store_true",
                        help="以 Zotero 为准覆盖已有值（默认只补空白）")
    parser.add_argument("--show", type=int, default=8, help="dry-run 展示的样本条数")
    args = parser.parse_args()
    diff_fn = _diff_overwrite if args.overwrite else _diff_missing

    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    keys = [r[0] for r in cursor.execute("SELECT DISTINCT item_key FROM figures")]
    print(f"figures 条目数: {len(keys)}")

    meta_map = get_zotero_meta_map(keys)
    print(f"Zotero 命中:   {len(meta_map)}")

    cursor.execute("SELECT item_key, title, year, journal, journal_abbr, authors, "
                   "authors_norm FROM figures")
    rows = cursor.fetchall()

    changes, field_counts = [], {f: 0 for f in FIELDS}
    for row in rows:
        item_key = row[0]
        new = meta_map.get(item_key)
        if not new:
            continue
        diff = diff_fn(row, new)
        if diff:
            changes.append((item_key, diff))
            for field in diff:
                field_counts[field] += 1

    mode = "覆盖" if args.overwrite else "仅补空白"
    print(f"模式:         {mode}")
    print(f"将变更行数:   {len(changes)}")
    print("按字段统计（行数）：")
    for field in FIELDS:
        print(f"  {field:14s} {field_counts[field]}")

    if args.dry_run:
        print(f"\n样本（前 {args.show} 条）：")
        for item_key, diff in changes[:args.show]:
            print(f"  {item_key}")
            for field, (old_val, new_val) in diff.items():
                if field in ("authors_norm",):
                    print(f"    {field}: <{len(str(old_val))}B> -> <{len(str(new_val))}B>")
                else:
                    print(f"    {field}: {old_val!r} -> {new_val!r}")
        conn.close()
        return

    now = int(time.time())
    for item_key, diff in changes:
        cols = ", ".join(f"{f}=?" for f in diff)
        vals = [diff[f][1] for f in diff] + [now, item_key]
        cursor.execute(f"UPDATE figures SET {cols}, indexed_at=? WHERE item_key=?", vals)
    # 清洗历史脏值：刊名为空却残留简称（全部是同一个错值 "中国科学: 地球科学"，
    # 2026-11-10 实测 392 行），前端会据此显示错误期刊。引擎加载时的兜底
    # journal_abbr_str("") 也返回空，所以清零后不会再生出新的值。
    cursor.execute("UPDATE figures SET journal_abbr='', indexed_at=? "
                   "WHERE (journal IS NULL OR journal='') "
                   "AND journal_abbr IS NOT NULL AND journal_abbr!=''", (now,))
    cleared = cursor.rowcount
    conn.commit()

    total = cursor.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
    empty_journal = cursor.execute(
        "SELECT COUNT(*) FROM figures WHERE journal IS NULL OR journal=''").fetchone()[0]
    empty_authors = cursor.execute(
        "SELECT COUNT(*) FROM figures WHERE authors IS NULL OR authors=''").fetchone()[0]
    zero_year = cursor.execute(
        "SELECT COUNT(*) FROM figures WHERE year IS NULL OR year=0").fetchone()[0]
    conn.close()

    print(f"\n写入完成，figures 总行数 {total}")
    print(f"清洗脏值：刊名空而残留简称 {cleared} 行")
    print(f"剩余缺失：期刊 {empty_journal} 行 / 作者 {empty_authors} 行 / 年份 {zero_year} 行")
    print("下一步：重启服务让缓存签名失效（_signature 的 MAX(indexed_at) 已变）")


if __name__ == "__main__":
    main()
