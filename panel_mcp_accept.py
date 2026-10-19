"""panel_mcp_accept.py — 工单§四 验收（可重复执行）。"""
import base64
import hashlib
import os
import sys

sys.path.insert(0, "D:/Zotero/fig_db")
import mcp_server as M

ok = []


def chk(name, cond, detail=""):
    ok.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# 1) panel 定向：用真实受益样本 RZI7LYJF Fig.3a（整图实得 ≈480px）
note, img = M._panel_payload("RZI7LYJF", "Fig. 3", "a")
gain = float(note.split("gain=")[1].split()[0])
chk("§四.1 panel 定向 gain>=1.5", gain >= 1.5, f"gain={gain} {note}")
chk("§四.1 text 含 native/returned/gain", all(k in note for k in ("native=", "returned=", "gain=")))
chk("§四.1 返回图像流", img is not None and len(base64.b64decode(img.to_image_content().data)) > 10000)

# 2) get_figure_image 父图+字母
r = M.get_figure_image("JYGMPNRM_Fig__4_p7.webp", panel="a")
# 命中面板的判据：图像流走 data 分支（path 为 None）且 text 含 native=
chk("§四.2 get_figure_image(panel='a') 命中面板",
    "native=" in r[0] and getattr(r[1], "path", None) is None and getattr(r[1], "data", None),
    r[0].split("\n")[-1][:70])

# 3) 默认路径逐字节一致（3 样本）
same = True
for s in ["JYGMPNRM_Fig__1_p2.webp", "JYGMPNRM_Fig__4_p7.webp", "JYGMPNRM_Fig__7_p9.webp"]:
    raw = base64.b64decode(M.get_figure_image(s)[1].to_image_content().data)
    disk = open(os.path.join(M.IMAGE_DIR, s), "rb").read()
    same &= hashlib.sha256(raw).digest() == hashlib.sha256(disk).digest()
chk("§四.3 默认路径 3 样本 sha256 一致", same)

# 4) 面板不存在回退并注明
r = M.search_figures(query="lake level", item_key="JYGMPNRM", panel="z")
chk("§四.4 面板缺失回退+注明", "未收录" in r[0] and "回退整图" in r[0], r[0].replace("\n", " | ")[:90])
chk("§四.4 回退给的是整图行", r[1].path.name.endswith("Fig__4_p7.webp"))

# 5) panel_pick=first
r = M.search_figures(query="lake level", item_key="JYGMPNRM", panel_pick="first")
chk("§四.5 panel_pick='first'", "panel=a" in r[0])

# 6) upscale_to 不超原生
note, _ = M._panel_payload("JYGMPNRM", "Fig. 4", "b", crop_mode="upscale_to")
ret = note.split("returned=")[1].split()[0]
chk("§三.2 upscale_to 不超原生", ret == "1397x562", f"returned={ret} native=1397x562")

print()
bad = [n for n, c, _ in ok if not c]
print(f"== {len(ok) - len(bad)}/{len(ok)} PASS ==")
sys.exit(1 if bad else 0)
