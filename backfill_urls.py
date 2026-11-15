"""从 Zotero 库回填 figures.url（原文网址）。

优先 itemData 的 url 字段；为空时用 DOI 拼 https://doi.org/<doi>。
只填空行（可重入）：WHERE url IS NULL OR url = ''。入库后跑一次即可。

用法：python backfill_urls.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from engine import DB_PATH, FigureDB

SQL = """
SELECT i.key,
  (SELECT v.value FROM itemData d JOIN itemDataValues v ON v.valueID = d.valueID
     JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'url') AS url,
  (SELECT v.value FROM itemData d JOIN itemDataValues v ON v.valueID = d.valueID
     JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'DOI') AS doi
FROM items i
"""


def read_zotero_urls():
    """读 Zotero 库。Zotero 运行时库被独占锁，必须先拷快照（含 -wal）再读。"""
    zdir = config.zotero_dir()
    src = os.path.join(zdir, "zotero.sqlite")
    if not os.path.isfile(src):
        raise SystemExit(f"找不到 Zotero 库：{src}")
    # Zotero 运行时主库被独占锁；只读快照优先用 Zotero 自己写的 .bak（一定没锁）
    backup = src + ".bak"
    if os.path.isfile(backup) and os.path.getsize(backup) > 1024:
        src = backup
    import shutil
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="zfb-urls-")
    snap = os.path.join(tmpdir, "zotero.sqlite")
    shutil.copy2(src, snap)
    for suffix in ("-wal", "-shm"):
        side = src + suffix
        if os.path.isfile(side):
            try:
                shutil.copy2(side, snap + suffix)
            except OSError:
                pass
    conn = sqlite3.connect(snap, timeout=5)
    mapping = {}
    for key, url, doi in conn.execute(SQL):
        if not key:
            continue
        value = (url or "").strip()
        if not value and doi:
            bare = doi.strip()
            if bare.lower().startswith("10."):
                value = "https://doi.org/" + bare
        if value:
            mapping[key.upper()] = value
    conn.close()
    shutil.rmtree(tmpdir, ignore_errors=True)
    return mapping


def backfill(dry_run=False):
    FigureDB()   # 触发建表/补列（_init_db 里 ALTER ADD COLUMN url）
    mapping = read_zotero_urls()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    rows = conn.execute("SELECT DISTINCT item_key FROM figures WHERE url IS NULL OR url = ''").fetchall()
    pending = [(r[0], mapping[r[0].upper()]) for r in rows if r[0].upper() in mapping]
    print(f"Zotero 有网址条目 {len(mapping)}；库内待补 {len(rows)}；可补 {len(pending)}")
    if dry_run:
        for key, url in pending[:5]:
            print("  ", key, url)
        conn.close()
        return len(pending)
    for key, url in pending:
        conn.execute("UPDATE figures SET url = ? WHERE item_key = ? AND (url IS NULL OR url = '')",
                     (url, key))
    conn.commit()
    left = conn.execute("SELECT COUNT(DISTINCT item_key) FROM figures WHERE url IS NULL OR url = ''").fetchone()[0]
    filled = conn.execute("SELECT COUNT(*) FROM figures WHERE url IS NOT NULL AND url <> ''").fetchone()[0]
    conn.close()
    print(f"已写入 {len(pending)} 篇；仍无网址 {left} 篇；有网址图行 {filled}")
    return len(pending)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
