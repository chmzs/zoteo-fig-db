# -*- coding: utf-8 -*-
"""夜跑收尾：隔离条目救回 -> 生成总结报告 -> 重启 zoteo-fig-db 画廊 -> curl 验证。"""

import sys
import os
import subprocess
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PY = r"D:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\python.exe"
GALLERY_EXE = r"D:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\zoteo-fig-db.exe"


def run_py(script):
    print(f"\n===== {script} =====", flush=True)
    p = subprocess.run([PY, os.path.join(BASE, script)], capture_output=True, text=True, encoding="utf-8")
    tail_lines = (p.stdout or "").splitlines()[-25:]
    print("\n".join(tail_lines))
    if p.returncode != 0:
        print("STDERR:", (p.stderr or "")[-800:])
    return p.returncode


def main():
    # 1. 救回 zero-fig 论文（并排/下方版式回退修复后重跑）
    run_py("rescue_zero.py")

    # 2. 救回隔离条目（修复后的降级代码重跑）
    run_py("reindex_quarantine.py")

    # 3. 生成总结报告
    run_py("summarize_run.py")

    # 4. 重启画廊服务（杀旧进程 -> 无浏览器后台拉起）
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process zoteo-fig-db -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True)
    time.sleep(1)
    env = dict(os.environ)
    env["NO_BROWSER"] = "1"
    subprocess.Popen([GALLERY_EXE, os.path.join(BASE, "server.py")],
                     cwd=BASE, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    print("\n===== gallery restart =====")
    subprocess.run(["curl", "-s", "-m", "5", "-w", "\nstats: HTTP %{http_code}\n",
                    "-o", os.devnull, "http://127.0.0.1:5173/api/stats"])
    subprocess.run(["curl", "-s", "-m", "10", "-w", "\nsearch: %{time_total}s\n",
                    "-o", os.devnull, "http://127.0.0.1:5173/api/search?q=warming&top_k=5"])
    print("\nFINISH_OK")


if __name__ == "__main__":
    main()
