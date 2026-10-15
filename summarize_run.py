# -*- coding: utf-8 -*-
"""生成夜跑中文总结报告（FINAL_DONE 后执行）：各家族统计 / 隔离聚类 / DB 总览 / 修复记录。"""

import sys
import os
import json
import glob
import sqlite3
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from batch_master import classify

def main():
    st = {}
    sf = os.path.join(BASE_DIR, "batch_state.json")
    if os.path.exists(sf):
        st = json.load(open(sf, encoding="utf-8"))

    fam_figs = defaultdict(int)
    fam_paps = defaultdict(set)
    qcluster = Counter()
    qlines = []
    for f in glob.glob(os.path.join(BASE_DIR, "batch_tmp", "*.quarantine.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
                qcluster[(o.get("err", "") or "")[:60]] += 1
                qlines.append(o.get("item_key"))
            except Exception:
                pass
    for q in st.get("quarantined", []):
        qcluster[(q.get("err", "") or "")[:60]] += 1

    db = sqlite3.connect(os.path.join(BASE_DIR, "zotero-figures.sqlite"))
    c = db.cursor()
    total, paps = c.execute("SELECT COUNT(*), COUNT(DISTINCT item_key) FROM figures").fetchone()
    for k, j in c.execute("SELECT DISTINCT item_key, journal FROM figures"):
        fam = classify("", j)
        fam_paps[fam].add(k)
    for j, n in c.execute("SELECT journal, COUNT(*) FROM figures GROUP BY journal"):
        fam_figs[classify("", j)] += n
    vers = dict(c.execute("SELECT extractor_version, COUNT(*) FROM figures GROUP BY extractor_version"))
    db.close()

    lines = ["# zoteo-fig-db 夜跑总结报告", ""]
    fd = os.path.join(BASE_DIR, "FINAL_DONE.json")
    if os.path.exists(fd):
        lines.append(f"- 完成时间：{json.load(open(fd, encoding='utf-8')).get('ts')}")
    lines += [
        f"- 图库总量：**{total} 张图 / {paps} 篇文献**",
        f"- 抽取版本分布：{vers}",
        "",
        "## 各出版商家族",
        "| 家族 | 文献 | 图 |",
        "|---|---|---|",
    ]
    for fam in sorted(fam_paps, key=lambda f: -fam_figs[f]):
        lines.append(f"| {fam} | {len(fam_paps[fam])} | {fam_figs[fam]} |")
    lines += ["", "## 隔离清单（聚类）"]
    if qcluster:
        for err, n in qcluster.most_common():
            lines.append(f"- {n}x  {err}")
    else:
        lines.append("- 无")
    lines += [
        "",
        "## 修复记录",
        "- 假题注防御：题注上方无图形证据→拒绝（Elsevier 正文并入题注块问题）",
        "- get_drawings / get_text(dict) 异常降级：MuPDF nested-graphics 不再整篇阵亡",
        "- onnxruntime 线程限 2 + WORKERS=4：吞吐 ~2x",
        "- 位图元数据免解码（get_image_info）：提取提速",
        "- 期刊简称链：字段合法性校验（首字母子序列/词前缀）+ 同刊共识，拦截元数据错配脏值",
    ]
    report = "\n".join(lines) + "\n"
    with open(os.path.join(BASE_DIR, "NIGHT_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)

if __name__ == "__main__":
    main()
