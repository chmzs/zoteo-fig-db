"""回填缩略图：为历史行补 xxx.thumb.webp（480px / q72）。

为什么需要：缩略图逻辑是后加的，实测只有 237/16048 张存在 .thumb.webp，
其余卡片的 thumb_name 为空 → 前端回落 /image/ 加载原图（均 84KB），
画廊首屏与跨设备访问都白白多传约 75% 字节。

用法：python backfill_thumbs.py [--limit N] [--dry-run]
可重入：只处理缺缩略图的行；重复运行无副作用。
"""

import argparse
import os
import sqlite3
import time

from PIL import Image

from engine import DB_PATH, THUMB_MAX_SIDE, WEBP_QUALITY


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="本次最多处理多少张（0=全部）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=60)
    rows = conn.execute(
        "SELECT id, image_path FROM figures "
        "WHERE image_path IS NOT NULL AND image_path LIKE '%.webp'"
    ).fetchall()
    missing = [
        (row_id, path) for row_id, path in rows
        if path and not os.path.exists(path[:-5] + ".thumb.webp")
    ]
    print(f"rows={len(rows)} missing_thumb={len(missing)}")
    if args.dry_run:
        return
    if args.limit:
        missing = missing[:args.limit]

    started = time.perf_counter()
    done = failed = 0
    for idx, (row_id, path) in enumerate(missing, 1):
        thumb_path = path[:-5] + ".thumb.webp"
        try:
            with Image.open(path) as image:
                image.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
                image.save(thumb_path, "WEBP", quality=WEBP_QUALITY, method=4)
            done += 1
        except Exception:
            failed += 1
        if idx % 2000 == 0:
            rate = idx / max(time.perf_counter() - started, 1e-6)
            print(f"  {idx}/{len(missing)}  {rate:.0f} 张/秒  剩余 {(len(missing)-idx)/max(rate,1)/60:.1f} 分钟", flush=True)
    elapsed = time.perf_counter() - started
    print(f"done={done} failed={failed} elapsed={elapsed/60:.1f}分钟")


if __name__ == "__main__":
    main()
