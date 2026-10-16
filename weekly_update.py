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
    maxts = dict(conn.execute("SELECT item_key, MAX(indexed_at) FROM figures GROUP BY item_key").fetchall())
    conn.close()
    fresh = [p for p in papers if p["item_key"] not in maxts]
    # 变更检测: PDF mtime 晚于该篇最后入库 >2min（拼接附件/重下载）→ 清场 redo
    changed = []
    for p in papers:
        ts = maxts.get(p["item_key"])
        if ts is None or not p.get("pdf_path"):
            continue
        try:
            mt = os.path.getmtime(p["pdf_path"])
        except OSError:
            continue
        if mt - ts > 120:
            changed.append(p)
    log(f"incremental: 新增 {len(fresh)} 篇 / 变更 {len(changed)} 篇")
    failed = []
    for p in fresh:
        try:
            indexer.index_papers([p])
        except Exception as e:
            failed.append((p["item_key"], (p.get("title") or "")[:40], type(e).__name__ + ": " + str(e)[:80]))
    if changed:
        import engine as _eng
        dbx = _eng.FigureDB()
        for p in changed:
            try:
                n_old = dbx.remove_item(p["item_key"])
                indexer.index_papers([p], force_reindex=True)
                log(f"  redo {p['item_key']} (清 {n_old} 旧行)")
            except Exception as e:
                failed.append((p["item_key"], (p.get("title") or "")[:40], "CHANGED " + type(e).__name__ + ": " + str(e)[:60]))
    if failed:
        import json as _j
        _j.dump(failed, open(os.path.join(BASE_DIR, "poison_failures.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"incremental: {len(failed)} 篇异常 -> poison_failures.json（键名/报错已记录）")
    log("incremental: 完成")

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
    try:
        import make_poison_report
        make_poison_report.main()
    except Exception as e:
        log(f"poison_report 生成失败: {e}")
    log("weekly_update done")
