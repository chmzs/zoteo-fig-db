# -*- coding: utf-8 -*-
"""weekly_update.py — 每周日 03:00 计划任务（zoteo-fig-db-weekly）：
1) 备份：sqlite backup API 快照 → zotero-figures.sqlite.bak（Zotero 式单份轮转，先备份后更新）
2) 增量入库：indexer 全扫（已入库 item_key 自动跳过，只提新论文）
3) 孤儿 GC：cache/figures 里删去无 DB 引用文件（含缩略图与 .bak 时代残留）
日志追加 weekly_update.log。"""
import os
import sys
import time
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
DB = os.path.join(BASE_DIR, "zotero-figures.sqlite")
BAK = DB + ".bak"
IMG_DIR = os.path.join(BASE_DIR, "cache", "figures")
LOG = os.path.join(BASE_DIR, "weekly_update.log")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def backup():
    src = sqlite3.connect(DB, timeout=30)
    dst = sqlite3.connect(BAK)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    log(f"backup ok -> {os.path.basename(BAK)} ({os.path.getsize(BAK)//2**20}MB)")


def incremental():
    import indexer
    papers = indexer.get_zotero_items_with_pdfs(limit=None)
    conn = sqlite3.connect(DB, timeout=30)
    have = {r[0] for r in conn.execute("SELECT DISTINCT item_key FROM figures").fetchall()}
    conn.close()
    fresh = [p for p in papers if p["item_key"] not in have]
    if not fresh:
        log("incremental: 无新增条目")
        return
    log(f"incremental: 新条目 {len(fresh)} 篇，逐篇提取(单篇异常只记录)…")
    failed = 0
    for p in fresh:
        try:
            indexer.index_papers([p])
        except Exception:
            failed += 1
    if failed:
        log(f"incremental: {failed} 篇提取异常（毒 PDF/嵌套图形栈，跳过）")
    log(f"incremental: 入库 {n} 图")


def orphan_gc():
    conn = sqlite3.connect(DB, timeout=30)
    alive = set()
    for p, in conn.execute("SELECT image_path FROM figures").fetchall():
        if p:
            alive.add(os.path.basename(p))
            alive.add(p.replace(".webp", ".thumb.webp"))
    conn.close()
    removed = bytes_freed = 0
    for fn in os.listdir(IMG_DIR):
        if fn not in alive:
            fp = os.path.join(IMG_DIR, fn)
            try:
                bytes_freed += os.path.getsize(fp)
                os.remove(fp)
                removed += 1
            except OSError:
                pass
    log(f"orphan_gc: 删除孤儿 {removed} 个，释放 {bytes_freed // 2**20}MB")


if __name__ == "__main__":
    backup()
    incremental()
    orphan_gc()
    log("weekly_update done")
