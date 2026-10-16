# -*- coding: utf-8 -*-
"""
夜间全库批次提取主控（publisher/刊名家族分组 + 断点续跑 + 超时二分 + 逐批 QC）
- 状态: batch_state.json（done/quarantined/batches）
- 输出: batch.log（nohup 重定向）、FINAL_DONE.json
- 单批 = BATCH_SIZE 篇，子进程 worker；批超时 TIMEOUT 秒 → 对半重跑；单篇仍超时 → 隔离
"""

import os
import sys
import json
import time
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine import FigureDB
from indexer import get_zotero_items_with_pdfs

PY = r"D:\Users\chmzs\Documents\Pixi_env\.pixi\envs\geo\python.exe"
WORKER = os.path.join(BASE_DIR, "batch_worker.py")
STATE = os.path.join(BASE_DIR, "batch_state.json")
TMP_DIR = os.path.join(BASE_DIR, "batch_tmp")
BATCH_SIZE = 60
TIMEOUT = 22 * 60

from family_rules import JOURNAL_RULES, EXACT_FAMILY, _journal_family



def classify(publisher, journal):
    pl = (publisher or "").lower()
    jl = (journal or "").lower()
    if any('\u4e00' <= c <= '\u9fff' for c in (journal or "") + (publisher or "")):
        return "cn"
    # 出版商强信号优先（覆盖刊名启发式拿不准的）
    if "amer geophysical" in pl or "american geophysical" in pl or "american meteorolog" in pl:
        return "agu"
    if "geoscienceworld" in pl or "geological society of america" in pl:
        return "gsw"
    if "aaas" in pl or "advancement" in pl:
        return "aaas"
    if "national academy" in pl:
        return "pnas"
    if "american chemical" in pl or pl.startswith("acs"):
        return "acs"
    # 刊名启发式主路由
    jf = _journal_family(jl)
    if jf:
        return jf
    # 无刊名时退回 publisher 家族
    if "geophysical union" in pl:
        return "agu"
    if "elsevier" in pl or "pergamon" in pl:
        return "elsevier"
    if "nature" in pl or "macmillan" in pl:
        return "nature"
    if "springer" in pl:
        return "springer"
    if "wiley" in pl or "online library" in pl or "online-library" in pl:
        return "wiley"
    if "copernicus" in pl:
        return "copernicus"
    if "oxford" in pl:
        return "oup"
    if "cambridge" in pl:
        return "cambridge"
    if "taylor" in pl or "francis" in pl or "tandf" in pl:
        return "tandf"
    if "sage" in pl:
        return "sage"
    if "institute of physics" in pl or "iop " in pl or "physics web" in pl:
        return "iop"
    if "mdpi" in pl:
        return "mdpi"
    if "frontiers" in pl:
        return "frontiers"
    if "geological society" in pl:
        return "gsw"
    return "other"


ORDER = ["nature", "aaas", "agu", "elsevier", "wiley", "springer", "pnas", "copernicus",
         "iop", "cambridge", "oup", "tandf", "sage", "acs", "gsw", "mdpi", "frontiers", "other", "cn"]


def log(msg):
    print(f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"done": [], "quarantined": [], "batches": []}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def run_worker(items, prefix):
    """Returns list of completed item_keys, or None on timeout."""
    os.makedirs(os.path.dirname(prefix), exist_ok=True)
    jf = prefix + ".items.json"
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    with open(prefix + ".out.log", "w", encoding="utf-8") as out:
        p = subprocess.Popen([PY, WORKER, jf, prefix], stdout=out, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            return None
    done = []
    pp = prefix + ".papers.jsonl"
    if os.path.exists(pp):
        for line in open(pp, encoding="utf-8"):
            try:
                done.append(json.loads(line)["item_key"])
            except Exception:
                pass
    return done


def process_batch(st, items, tag, bi):
    prefix = os.path.join(TMP_DIR, f"{tag}_{bi}")
    done = run_worker(items, prefix)
    if done is None:
        if len(items) <= 1:
            st["quarantined"].append({"item_key": items[0]["item_key"],
                                      "pdf": items[0].get("pdf_path", ""), "err": "timeout-single"})
            save_state(st)
            log(f"  QUARANTINE(timeout) {tag}#{bi} {items[0]['item_key']}")
            return
        mid = len(items) // 2
        log(f"  {tag}#{bi} TIMEOUT -> split {mid}+{len(items) - mid}")
        process_batch(st, items[:mid], tag, f"{bi}a")
        process_batch(st, items[mid:], tag, f"{bi}b")
        return

    qf = prefix + ".quarantine.jsonl"
    qn = 0
    if os.path.exists(qf):
        for line in open(qf, encoding="utf-8"):
            try:
                st["quarantined"].append(json.loads(line))
                qn += 1
            except Exception:
                pass
    qc = {}
    qcf = prefix + ".qc.json"
    if os.path.exists(qcf):
        qc = json.load(open(qcf, encoding="utf-8"))

    done_set_existing = set(st["done"])
    st["done"].extend([k for k in done if k not in done_set_existing])
    st["batches"].append({"tag": tag, "bi": str(bi), "qc": qc, "quar": qn})
    save_state(st)
    log(f"  OK {tag}#{bi}: papers={qc.get('papers', '')} figs={qc.get('figs', '')} "
        f"zero={qc.get('zero_figs_papers', '')} extreme={qc.get('extreme_bbox', '')} "
        f"quar={qn} secs={qc.get('secs', '')}")


def main():
    db = FigureDB()
    st = load_state()
    done_set = set(st["done"])
    log("== master start: enumerating papers ==")
    papers = get_zotero_items_with_pdfs(limit=None)
    conn = db.get_conn()
    in_db = {r[0] for r in conn.execute("SELECT DISTINCT item_key FROM figures")}
    conn.close()
    todo = [p for p in papers if p["item_key"] not in done_set and p["item_key"] not in in_db]
    log(f"papers with local main-PDF: {len(papers)}; already in DB: {len(in_db)}; todo: {len(todo)}")

    groups = {}
    for p in todo:
        groups.setdefault(classify(p.get("publisher", ""), p.get("journal", "")), []).append(p)
    fams = [f for f in ORDER if f in groups] + sorted(set(groups) - set(ORDER))
    log("families: " + " | ".join(f"{f}:{len(groups[f])}" for f in fams))

    total = sum(-(-len(groups[f]) // BATCH_SIZE) for f in fams)
    bi_global = 0
    for fam in fams:
        items = groups[fam]
        nb = -(-len(items) // BATCH_SIZE)
        for bi in range(nb):
            bi_global += 1
            chunk = items[bi * BATCH_SIZE:(bi + 1) * BATCH_SIZE]
            log(f"[{bi_global}/{total}] family={fam} batch={bi} papers={len(chunk)}")
            process_batch(st, chunk, fam, bi)

    stats = db.get_stats()
    summary = {"done_items": len(st["done"]), "quarantined": len(st["quarantined"]),
               "db_stats": stats, "ts": time.strftime('%F %T')}
    with open(os.path.join(BASE_DIR, "FINAL_DONE.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    log("== ALL DONE: " + json.dumps(summary, ensure_ascii=False) + " ==")


if __name__ == "__main__":
    main()
