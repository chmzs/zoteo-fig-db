"""语法门：server.py 内嵌画廊 HTML 的 <script> JS。

教训（2026-10-28 实测）：HTML_CONTENT 是普通（非 raw）三引号串，Python 转义层
会吃掉反斜杠，产出浏览器侧非法 JS（如 replace(/\\\\/g) 求值后成 /\\/g，
SyntaxError: missing ) after argument list），整页交互全瘫但后端 API 照常健康。
ruff / py_compile 只查 Python 外层语法，对字符串内部的 JS 全盲（实测双绿）。

本门按导入语义 eval 该字符串，抽出每个 <script> 体，交 node --check 真判语法。
用法：python check_gallery_js.py [server.py 路径]（默认 ./server.py）
退出码 0 = 通过；1 = JS 有语法错（node 原文已打印）；2 = 门自身故障。
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_html(server_path: Path) -> str:
    """按 Python 导入语义取出 HTML_CONTENT 求值后的字符串（与运行时逐字节一致）。"""
    src = server_path.read_text(encoding="utf-8")
    marker = "HTML_CONTENT = "
    start = src.index(marker) + len(marker)
    end = src.index('\n"""', start) + 4
    html_src = src[start:end]
    return eval(html_src)  # 本仓库自有文件；必须走真实求值才能还原 Python 吃掉的转义


def check_scripts(html: str) -> int:
    node = shutil.which("node")
    if not node:
        print("FAIL: 找不到 node，无法检查画廊内嵌 JS（门依赖 node --check）")
        return 2
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    if not scripts:
        print("FAIL: HTML_CONTENT 里没抽到 <script> 块——结构变了，先修本门")
        return 2
    bad = 0
    for idx, js in enumerate(scripts):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=f"_script{idx}.js", delete=False, encoding="utf-8")
        with tmp:
            tmp.write(js)
        tmp_path = Path(tmp.name)
        try:
            result = subprocess.run(
                [node, "--check", str(tmp_path)],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        if result.returncode != 0:
            bad += 1
            print(f"FAIL: <script>#{idx} JS 语法错误（node --check）：")
            print((result.stderr or "").strip())
    return 1 if bad else 0


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "server.py"
    try:
        html = load_html(target)
    except (ValueError, SyntaxError) as exc:
        print(f"FAIL: 无法从 {target} 提取 HTML_CONTENT：{exc}")
        return 2
    rc = check_scripts(html)
    if rc == 0:
        print("OK: 画廊内嵌 JS 通过 node --check")
    return rc


if __name__ == "__main__":
    sys.exit(main())
