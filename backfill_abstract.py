"""backfill_abstract.py — 把 Zotero abstractNote 回填到存量 figures.context_text + FTS5。
只读 zotero.sqlite（复制后读），写 fig_db。幂等：重跑只补缺。"""
import os
import shutil
import sqlite3
import sys
import tempfile

BASE = "D:/Zotero/fig_db"
FIGDB = os.path.join(BASE, "zotero-figures.sqlite")
ZOT = r"D:\Zotero\zotero.sqlite"

tmp = os.path.join(tempfile.gettempdir(), "_zot_backfill.sqlite")
shutil.copy2(ZOT, tmp)
z = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
abs_map = dict(z.execute("""
    SELECT i2.key, v.value FROM items i2
    JOIN itemData d ON d.itemID=i2.itemID
    JOIN fields f ON f.fieldID=d.fieldID
    JOIN itemDataValues v ON v.valueID=d.valueID
    WHERE f.fieldName='abstractNote'
""").fetchall())
z.close()
os.remove(tmp)
print(f"Zotero abstract 条目: {len(abs_map)}")

c = sqlite3.connect(FIGDB, timeout=60)
rows = c.execute("SELECT id, item_key, fig_no, caption, title, journal, context_text FROM figures").fetchall()
updated = skipped = 0
for rid, ik, fn, cap, title, journal, ctx in rows:
    ab = (abs_map.get(ik) or "").strip()
    if not ab:
        skipped += 1
        continue
    if ctx and ctx.strip() == ab:
        skipped += 1
        continue
    c.execute("UPDATE figures SET context_text=? WHERE id=?", (ab, rid))
    # FTS5 external-content：重写该 rowid 的索引行
    try:
        c.execute("INSERT OR REPLACE INTO fts_figures (rowid, fig_no, caption, title, journal, context_text) "
                  "VALUES (?,?,?,?,?,?)", (rid, fn, cap, title, journal, ab))
    except sqlite3.OperationalError:
        pass
    updated += 1
c.commit()

# 校验
nonempty = c.execute("SELECT COUNT(*) FROM figures WHERE length(context_text)>0").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
fts_hit = c.execute("SELECT COUNT(*) FROM fts_figures WHERE fts_figures MATCH 'monsoon'").fetchone()[0]
print(f"回填 {updated} 行，跳过 {skipped}（无 abstract 或已一致）")
print(f"context_text 非空: {nonempty}/{total}")
print(f"FTS 'monsoon' 命中: {fts_hit}")
c.close()
