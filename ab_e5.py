# -*- coding: utf-8 -*-
"""A/B：Granite-fp32 vs MiniLM 全库 caption 编码 + 20 查询 top-5 并排对比。
不动生产库——Granite 向量存临时 npy；输出 ab_report_e5.txt 供目检。"""
import os
import sys
import time
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from engine import FigureDB

md = os.path.join(BASE, "models", "multilingual-e5-small")


class GEnc:
    def __init__(self):
        self.tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
        self.tok.enable_truncation(128)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(os.path.join(md, "model_int8.onnx"), sess_options=so,
                                         providers=["CPUExecutionProvider"])

    def batch(self, texts):
        encs = [self.tok.encode(t) for t in texts]
        ml = max(len(e.ids) for e in encs)
        ids = np.zeros((len(encs), ml), dtype=np.int64)
        mask = np.zeros((len(encs), ml), dtype=np.int64)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        out = self.sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0].astype(np.float32)
        m = mask[:, :, None].astype(np.float32)
        v = (out * m).sum(1) / np.clip(m.sum(1), 1, None)
        return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def main():
    db = FigureDB()
    conn = db.get_conn()
    rows = conn.execute("SELECT id, embedding, caption, title, journal, fig_no, year FROM figures").fetchall()
    conn.close()
    ids = np.array([r[0] for r in rows])
    meta = {r[0]: r for r in rows}
    print(f"figures: {len(rows)}", flush=True)

    # ---- MiniLM 侧：直接用库里 embedding ----
    M = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])

    # ---- Granite 侧：全库重编码（断点缓存） ----
    cache = os.path.join(BASE, "cache", "ab_e5_mat.npy")
    cache_ids_p = os.path.join(BASE, "cache", "ab_e5_ids.npy")
    if os.path.exists(cache) and os.path.exists(cache_ids_p):
        G = np.load(cache); gids = np.load(cache_ids_p)
        print(f"granite cache hit: {G.shape}", flush=True)
        if not np.array_equal(gids, ids):
            print("id mismatch, rebuild", flush=True); G = None
    else:
        G = None
    if G is None:
        g = GEnc()
        t0 = time.time()
        outs = []
        B = 64
        for i in range(0, len(rows), B):
            outs.append(g.batch(['passage: ' + (r[2] or '')[:480] for r in rows[i:i+B]]))
            if (i // B) % 25 == 0:
                print(f"  encode {i}/{len(rows)} ({time.time()-t0:.0f}s)", flush=True)
        G = np.vstack(outs)
        np.save(cache, G); np.save(cache_ids_p, ids)
        print(f"granite encoded in {time.time()-t0:.0f}s -> cache", flush=True)

    # ---- 20 查询对比 ----
    QUERIES = [
        "全新世温度重建", "夏季风 千年尺度变化", "粉尘 沉积 记录", "珊瑚 海平面",
        "花粉 植被 分辨率", "同位素 分馏 温度", "冰芯 温室气体", "植被起火 生物群系",
        "洞穴次生 石笋 氧同位素", "湖相 沉积 纹层",
        "Holocene temperature reconstruction", "Asian summer monsoon orbital forcing",
        "dust deposition North Pacific", "coral sea level 8.2 ka",
        "pollen-based biome reconstruction", "speleothem oxygen isotope annotation",
        "ice core CO2 concentration", " wildfire charcoal accumulation",
        "foraminifera Mg/Ca paleothermometry", "loess magnetic susceptibility monsoon",
    ]
    gq = GEnc().batch(['query: ' + q for q in QUERIES])
    from engine import MiniLMEncoder
    mq = MiniLMEncoder()
    mm = np.stack([np.asarray(mq.encode(q), dtype=np.float32) for q in QUERIES])

    lines = ["# e5-small(int8) vs MiniLM —— 20 查询 top-5 对比", ""]
    for qi, q in enumerate(QUERIES):
        gs = G @ gq[qi]; ms = M @ mm[qi]
        gtop = ids[np.argsort(-gs)[:5]]; mtop = ids[np.argsort(-ms)[:5]]
        overlap = len(set(gtop) & set(mtop))
        lines.append(f"## Q: {q}   (overlap {overlap}/5)")
        lines.append("  e5:")
        for fid in gtop:
            r = meta[fid]; lines.append(f"    [{gs[ids==fid][0]:.3f}] {r[4][:18]:18s} {r[5]:10s} {r[2][:56]}")
        lines.append("  MiniLM:")
        for fid in mtop:
            r = meta[fid]; lines.append(f"    [{ms[ids==fid][0]:.3f}] {r[4][:18]:18s} {r[5]:10s} {r[2][:56]}")
        lines.append("")
    out = os.path.join(BASE, "ab_report_e5.txt")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("REPORT ->", out, flush=True)


if __name__ == "__main__":
    main()
