"""panel_gate.py — 夜跑面板复核门禁（§八.3：误切率>5% 触发回退）。

扫描 batch_tmp/panel_qc_night*/report.jsonl（dry-run 产物），逐面板客观判据：
  F1 字母不连续/重复（题注声明数 ≠ 几何块数的漏网）
  F2 面板框两两重叠 >10%（小框）或 >25%（大框）
  F3 碎条带：min(px 边) < 120
  F4 题注自重复（"Fig. 4. Fig. 4a" 式吞并）
  F5 面板框越出父区
flagged/total > 5% 或 F1>0 → exit 1（链里据此 DELETE origin='panel'）。
"""
import glob
import json
import re
import sys

reports = glob.glob("D:/Zotero/fig_db/batch_tmp/panel_qc_night*/report.jsonl")
if not reports:
    print("GATE: 无复核报告（视为无面板, OK）")
    sys.exit(0)

total = flagged = 0
f1 = 0
details = []
for rp in reports:
    for line in open(rp, encoding="utf-8"):
        r = json.loads(line)
        reg = [float(v) for v in r["region_pt"]]
        letters = [p["letter"] for p in r["panels"]]
        expect = "abcdefghij"[:len(letters)]
        if "".join(sorted(letters)) != expect:
            f1 += 1
            details.append(("F1", r["item_key"], r["parent_fig"], letters))
        bs = [[float(v) for v in p["bbox_pt"]] for p in r["panels"]]
        for i in range(len(bs)):
            for j in range(i + 1, len(bs)):
                a, b = bs[i], bs[j]
                ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
                iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
                amin = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
                ov = ix * iy / amin if amin else 0
                if ov > (0.10 if amin < 40000 else 0.25):
                    flagged += 1
                    details.append(("F2", r["item_key"], r["parent_fig"], f"{letters[i]}/{letters[j]}={ov:.0%}"))
        for p in r["panels"]:
            if not p["px"]:
                continue
            total += 1
            b = [float(v) for v in p["bbox_pt"]]
            bad = False
            if min(p["px"]) < 120:
                bad = True
                details.append(("F3", r["item_key"], p["fig_no"], p["px"]))
            cap = p["caption"]
            m = re.match(r"^(Fig(?:ure)?\.?\s*S?\d+)", cap, re.I)
            if m and cap.lower().count(re.sub(r"[^a-z0-9]", "", m.group(1).lower())) > 1:
                bad = True
                details.append(("F4", r["item_key"], p["fig_no"], cap[:60]))
            if b[0] < reg[0]-3 or b[1] < reg[1]-3 or b[2] > reg[2]+3 or b[3] > reg[3]+3:
                bad = True
                details.append(("F5", r["item_key"], p["fig_no"], [round(v) for v in b], [round(v) for v in reg]))
            if bad:
                flagged += 1

ratio = flagged / total if total else 0.0
print(f"GATE: 报告 {len(reports)} 份 / 面板 {total} / 可疑 {flagged} ({ratio:.1%}) / F1 结构违规 {f1}")
for d in details[:25]:
    print("   ", d)
sys.exit(1 if (f1 > 0 or ratio > 0.05) else 0)
