"""backfill_authors_norm.py — 回填存量 figures.authors_norm（全部作者，非仅第一作者）。
从 zotero.sqlite 读每篇全部作者 → author_norm.build_authors_norm → UPDATE figures + 无需动 FTS
（authors_norm 不进 FTS5，走内存过滤）。幂等。"""
import os
import shutil
import sqlite3
import sys
import tempfile

BASE = "D:/Zotero/fig_db"
sys.path.insert(0, BASE)
from author_norm import build_authors_norm
from engine import DB_PATH

ZOT = r"D:\Zotero\zotero.sqlite"
tmp = os.path.join(tempfile.gettempdir(), "_zot_auth.sqlite")
shutil.copy2(ZOT, tmp)
z = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)

# item_key -> [全部作者，按 orderIndex]
rows = z.execute("""
    SELECT i.key, c.firstName, c.lastName, ic.orderIndex
    FROM itemCreators ic
    JOIN creators c ON ic.creatorID = c.creatorID
    JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
    JOIN items i ON ic.itemID = i.itemID
    WHERE ct.creatorType = 'author'
    ORDER BY i.key, ic.orderIndex
""").fetchall()
z.close()
os.remove(tmp)

by_key = {}
for key, first, last, _oi in rows:
    f = (first or "").strip()
    l = (last or "").strip()
    full = f"{f} {l}".strip() if f else l
    if full:
        by_key.setdefault(key, []).append(full)
print(f"Zotero 作者映射: {len(by_key)} 条目")

from engine import FigureDB
FigureDB()  # 触发 schema 迁移（authors_norm 列）
c = sqlite3.connect(DB_PATH, timeout=60)
fig_keys = [r[0] for r in c.execute("SELECT DISTINCT item_key FROM figures")]
updated = skipped = 0
for ik in fig_keys:
    authors = by_key.get(ik)
    if not authors:
        skipped += 1
        continue
    norm = build_authors_norm(authors)
    c.execute("UPDATE figures SET authors_norm=? WHERE item_key=?", (norm, ik))
    updated += 1
c.commit()

# 校验
nonempty = c.execute("SELECT COUNT(*) FROM figures WHERE length(authors_norm)>0").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
print(f"回填 {updated} 个 item（{skipped} 个无作者跳过）")
print(f"authors_norm 非空行: {nonempty}/{total}")
# 抽样看效果
for ik, norm in c.execute("SELECT item_key, authors_norm FROM figures WHERE length(authors_norm)>0 LIMIT 3"):
    print(f"  {ik}: {norm[:120]}")
c.close()
