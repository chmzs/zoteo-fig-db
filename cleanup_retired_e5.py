"""清理已退役的 e5 模型残留（定时任务用）。

守卫（任一不满足就中止，不删任何文件）：
1. models/granite-97m-r2/model_int8.onnx 存在
2. engine.MODEL_DIR 指向 granite-97m-r2
3. 库里抽样 20 行向量与当前模型一致性 > 0.99（确认全库确实在 granite 空间）
4. 项目根没有 `keep_e5` 标记文件（临时反悔开关）

用法：python cleanup_retired_e5.py [--dry-run]
日志：追加到 cache/cleanup.log
"""

import argparse
import os
import random
import shutil
import sqlite3
import sys
import time

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import DB_PATH, MODEL_DIR, Encoder  # noqa: E402

TARGETS = [
    os.path.join(BASE_DIR, "cache", "_retired", "multilingual-e5-small"),
    os.path.join(BASE_DIR, "cache", "_model_backup"),
]
KEEP_MARKER = os.path.join(BASE_DIR, "keep_e5")
LOG_PATH = os.path.join(BASE_DIR, "cache", "cleanup.log")


def log(message):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def guards():
    granite = os.path.join(BASE_DIR, "models", "granite-97m-r2", "model_int8.onnx")
    if not os.path.exists(granite):
        return "granite 模型不在 models/，中止（可能被移动或更换）"
    if os.path.basename(MODEL_DIR.rstrip("/\\")) != "granite-97m-r2":
        return f"engine.MODEL_DIR 指向 {MODEL_DIR}，不是 granite，中止"
    if os.path.exists(KEEP_MARKER):
        return "存在 keep_e5 标记文件，尊重保留意愿，中止"

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT caption, embedding FROM figures WHERE embedding IS NOT NULL").fetchall()
    finally:
        conn.close()
    if not rows:
        return "库里没有向量可校验，中止"
    random.seed(0)
    # 必须把 blob 与它自己的题注成对取出，分开取会配错行（踩过一次：报出 0.748 的假不一致）
    sample = random.sample(rows, min(20, len(rows)))
    encoder = Encoder()
    fresh = [encoder.encode(caption or "") for caption, _blob in sample]
    scores = []
    for (caption, blob), vector in zip(sample, fresh):
        stored = np.frombuffer(blob, dtype=np.float32)
        scores.append(float((stored * vector).sum()))
    mean_cos = sum(scores) / len(scores)
    if mean_cos < 0.99:
        return f"库内向量与 granite 一致性仅 {mean_cos:.3f}，中止（可能在别的模型空间）"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    existing = [path for path in TARGETS if os.path.exists(path)]
    if not existing:
        log("没有可清理的 e5 残留（已清理过）")
        return
    freed = sum(size_of(path) for path in existing)
    log(f"待清理 {len(existing)} 项，共 {freed/1048576:.1f} MB：")
    for path in existing:
        log(f"  {path}  {size_of(path)/1048576:.1f} MB")

    reason = guards()
    if reason:
        log(f"守卫拦截：{reason}")
        return
    if args.dry_run:
        log("dry-run：未删除任何文件")
        return
    for path in existing:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            log(f"已删除 {path}")
        except OSError as exc:
            log(f"删除失败 {path}: {exc}")
    log(f"清理完成，释放约 {freed/1048576:.1f} MB")


if __name__ == "__main__":
    main()
