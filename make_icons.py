"""从母版 PNG 生成 favicon 与 Windows 多尺寸 ICO。

为什么是 PNG 母版：Edge headless 在这个 SVG 上会按 512px 渲染再截左上半，
栅格化结果被裁（2026-11-20 实测，三种写法都一样）。可用的路径是浏览器截图
（assets/_rast.html 把 SVG 摆在洋红底上 512×512），再用本脚本键掉背景色、
trim、补 8% 边距、逐尺寸 LANCZOS 缩放。

重新生成母版（换 logo 时）：
  1. 把新 SVG 存成 assets/logo-source.svg（同时复制一份到 static/logo.svg 供网页用）
  2. 浏览器打开 assets/_rast.html，截图整页，存成 assets/_shot.png
  3. python make_icons.py

产物：assets/zoteo-fig-db.ico（快捷方式图标）+ static/favicon.ico（网页标签页）
"""

import pathlib
import sys

from PIL import Image

BASE = pathlib.Path(__file__).resolve().parent
SHOT = BASE / "assets" / "_shot.png"
MASTER = BASE / "assets" / "logo-master.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)
BOX = 512          # 截图里 SVG 占的边长（assets/_rast.html 固定 512）
PAD_RATIO = 0.08   # 四周留白，保证任何尺寸下视觉居中


def key_out_background(shot_path):
    """洋红底 (#ff00ff) 键成全透明。图标本身只用 slate/cyan/#e2e8f0，不含洋红。"""
    with Image.open(shot_path) as shot:
        rgb = shot.convert("RGB").crop((0, 0, BOX, BOX))
    alpha = Image.new("L", rgb.size, 0)
    src, dst = rgb.load(), alpha.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = src[x, y]
            dst[x, y] = 0 if (abs(r - 255) + abs(b - 255) + g) < 60 else 255
    rgba = rgb.convert("RGBA")
    rgba.putalpha(alpha)
    bbox = rgba.getbbox()
    if not bbox:
        raise SystemExit("键控后全是透明：确认截图背景是洋红")
    return rgba.crop(bbox)


def build_master():
    if not SHOT.exists():
        raise SystemExit(f"缺少母版截图 {SHOT}（见文件头注释的三步）")
    trimmed = key_out_background(SHOT)
    side = max(trimmed.size)
    pad = int(side * PAD_RATIO)
    square = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    square.paste(trimmed, ((square.width - trimmed.width) // 2,
                           (square.height - trimmed.height) // 2))
    square.resize((BOX, BOX), Image.LANCZOS).save(MASTER)
    return square


def main():
    master = build_master() if SHOT.exists() else Image.open(MASTER)
    images = [master.resize((size, size), Image.LANCZOS) for size in SIZES]

    assets_ico = BASE / "assets" / "zoteo-fig-db.ico"
    favicon_ico = BASE / "static" / "favicon.ico"
    frames = [(size, size) for size in SIZES]
    images[-1].save(assets_ico, format="ICO", sizes=frames)
    images[-1].save(favicon_ico, format="ICO", sizes=frames)

    for path in (assets_ico, favicon_ico):
        with Image.open(path) as check:
            got = sorted(s[0] for s in check.info.get("sizes", []))
        print(f"{path.relative_to(BASE)}  {path.stat().st_size} bytes  sizes={got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
