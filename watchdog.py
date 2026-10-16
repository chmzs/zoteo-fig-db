"""zoteo-fig-db 看门狗（由计划任务每 5 分钟用 pythonw 静默拉起）：
- .manual_stop 标记存在 → 尊重手动停止，退出
- 127.0.0.1:5173 可连 → 服务已活，退出
- 否则 detached 启动 zoteo-fig-db.exe server.py（NO_BROWSER=1 不弹浏览器）
"""

import os
import socket
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(BASE_DIR, ".manual_stop")
PYDIR = r"D:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo"
EXE = os.path.join(PYDIR, "zoteo-fig-db.exe")
SERVER = os.path.join(BASE_DIR, "server.py")


def port_alive():
    try:
        with socket.create_connection(("127.0.0.1", 5173), timeout=1.5):
            return True
    except OSError:
        return False


def main():
    if os.path.exists(MARKER) or port_alive() or not os.path.exists(EXE):
        return
    env = dict(os.environ)
    env["NO_BROWSER"] = "1"
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [EXE, SERVER],
        cwd=BASE_DIR,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


if __name__ == "__main__":
    main()
