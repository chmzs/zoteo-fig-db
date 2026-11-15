"""重建全库 embedding（只重算向量，不碰 PDF）。

为什么需要它：换 embedding 模型 / 换量化 / 换池化方式后，库里旧向量与新模型不在同一
空间，混用会让检索结果变成噪声。重抽取 PDF 要几小时，重算向量只要几分钟。

用法：
    python reembed.py                 # 全库重算
    python reembed.py --limit 200     # 试跑
    python reembed.py --dry-run       # 只统计，不写

安全性：逐条 UPDATE（可中断、可重入）；只改 embedding 与 indexed_at（后者用于让
FigureSearcher 的缓存签名失效，强制重建矩阵）。跑完必须重启 server，否则它的
Encoder 仍是旧模型，查询向量会落进旧空间。
"""

import argparse
import json
import os
import sqlite3
import time

import numpy as np

from engine import BASE_DIR, DB_PATH, EMB_DIM, Encoder

STATE_PATH = os.path.join(BASE_DIR, "cache", "reembed_state.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=64, help="每批提交条数")
    parser.add_argument("--chunk", type=int, default=0, help="本次最多处理多少行（0=不限；用于分批跑躲工具超时）")
    parser.add_argument("--reset", action="store_true", help="忽略游标从头开始")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    last_id = 0
    if os.path.exists(STATE_PATH) and not args.reset:
        try:
            last_id = int(json.load(open(STATE_PATH, encoding="utf-8")).get("last_id", 0))
        except (ValueError, OSError):
            last_id = 0

    encoder = Encoder()
    conn = sqlite3.connect(DB_PATH, timeout=60)
    query = "SELECT id, COALESCE(caption, '') FROM figures WHERE id > ? ORDER BY id"
    params = [last_id]
    if args.chunk:
        query += " LIMIT ?"
        params.append(args.chunk)
    query = query.replace("ORDER BY id", "ORDER BY id")
    rows = conn.execute(query, params).fetchall()
    print(f"rows to re-embed: {len(rows)} | dim={EMB_DIM}")
    if args.dry_run:
        sample = encoder.encode(rows[0][1] if rows else "")
        print(f"dry-run: sample dim={sample.shape[0]} norm={float(np.linalg.norm(sample)):.4f}")
        return

    started = time.perf_counter()
    done = 0
    bad_norm = 0
    for offset in range(0, len(rows), args.batch):
        chunk = rows[offset:offset + args.batch]
        vectors = encoder.encode_batch([caption for _, caption in chunk])
        updates = []
        for (row_id, _), vec in zip(chunk, vectors):
            if abs(float(np.linalg.norm(vec)) - 1.0) > 1e-3:
                bad_norm += 1
            updates.append((vec.astype(np.float32).tobytes(), time.time(), row_id))
        conn.executemany("UPDATE figures SET embedding = ?, indexed_at = ? WHERE id = ?", updates)
        conn.commit()
        with open(STATE_PATH, "w", encoding="utf-8") as state_file:
            json.dump({"last_id": chunk[-1][0]}, state_file)
        done += len(chunk)
        if done % (args.batch * 10) == 0 or done == len(rows):
            rate = done / max(time.perf_counter() - started, 1e-6)
            print(f"  {done}/{len(rows)}  {rate:.0f} 条/秒  预计剩余 {(len(rows)-done)/max(rate,1e-6)/60:.1f} 分钟", flush=True)
    conn.close()
    elapsed = time.perf_counter() - started
    print(f"done: {done} 条, {elapsed/60:.1f} 分钟, 异常范数 {bad_norm} 条")


if __name__ == "__main__":
    main()
