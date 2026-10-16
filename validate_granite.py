# -*- coding: utf-8 -*-
"""Granite-97M-r2 INT8 编码验证：tokenizers 直接吃 tokenizer.json，
ONNX CLS pooling + L2，用模型卡的 EN/DE/JA 黄金对照相似度矩阵校验。"""

import os
import sys
import time

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "models", "granite-embedding-97m-multilingual-r2")


class GraniteEncoder:
    """与 engine.MiniLMEncoder 同接口：encode(text)->list[384]，CLS pooling + L2。"""

    def __init__(self):
        self.tok = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        self.tok.enable_truncation(512)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self.sess = ort.InferenceSession(
            os.path.join(MODEL_DIR, "model_int8.onnx"),
            sess_options=opts, providers=["CPUExecutionProvider"])

    def encode_batch(self, texts):
        encs = [self.tok.encode(t) for t in texts]
        maxlen = max(len(e.ids) for e in encs)
        ids = np.zeros((len(encs), maxlen), dtype=np.int64)
        mask = np.zeros((len(encs), maxlen), dtype=np.int64)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        out = self.sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        vecs = out[:, 0, :]                       # CLS pooling
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return (vecs / np.clip(norms, 1e-9, None)).astype(np.float32)

    def encode(self, text):
        return self.encode_batch([text])[0].tolist()


QUERIES = [
    "What is the tallest mountain in Japan?",
    "Wer hat das Lied Achy Breaky Heart geschrieben?",
    "ドイツの首都はどこですか？",
]
PASSAGES = [
    "富士山は、静岡県と山梨県にまたがる活火山で、標高3776.12 mで日本最高峰の独立峰である。",
    "Achy Breaky Heart is a country song written by Don Von Tress. Originally titled Don't Tell My Heart and performed by The Marcy Brothers in 1991.",
    "Berlin ist die Hauptstadt und ein Land der Bundesrepublik Deutschland. Die Stadt ist mit rund 3,7 Millionen Einwohnern die bevölkerungsreichste Kommune Deutschlands.",
]
# 模型卡 (FP32) 期望值：对角线 EN->JA, DE->EN, JA->DE
EXPECT = [0.8869, 0.9577, 0.9112]


def main():
    enc = GraniteEncoder()

    # 1) token id 健康检查
    for t in [QUERIES[0], QUERIES[2], "图1 全新世温度重建"]:
        e = enc.tok.encode(t)
        unk = sum(1 for i in e.ids if i == enc.tok.token_to_id("[UNK]") or i is None)
        print(f"tok[{t[:18]!r}] n={len(e.ids)} unk={unk} first5={e.ids[:5]} last={e.ids[-1]}")

    # 2) 黄金对照相似度
    q = enc.encode_batch(QUERIES)
    p = enc.encode_batch(PASSAGES)
    sim = q @ p.T
    print("\ncos_sim matrix (rows=EN/DE/JA queries, cols=JA/EN/DE passages):")
    for r in sim:
        print("  " + "  ".join(f"{v:.4f}" for v in r))
    diag = [sim[i, i] for i in range(3)]
    ok = True
    for i, (d, e) in enumerate(zip(diag, EXPECT)):
        rowmax = sim[i].argmax()
        good = d >= 0.8 and rowmax == i and abs(d - e) < 0.08
        ok = ok and good
        print(f"pair{i}: diag={d:.4f} expect={e:.4f} rowargmax={rowmax} -> {'PASS' if good else 'FAIL'}")

    # 3) 中→英跨语言冒烟（我们真实场景）
    zh = ["全新世温度重建"]
    en = ["Holocene temperature reconstruction of the past 6000 years",
          "Mid-latitude dust cycle and aeolian deposition"]
    s = enc.encode_batch(zh) @ enc.encode_batch(en).T
    print(f"\nzh->en: related={s[0,0]:.4f} unrelated={s[0,1]:.4f} -> "
          f"{'PASS' if s[0,0] > s[0,1] + 0.15 else 'CHECK'}")

    # 4) 吞吐
    t0 = time.time()
    enc.encode_batch([QUERIES[0]] * 100)
    dt = time.time() - t0
    print(f"throughput: {100/dt:.0f} texts/s (batched, 4 threads)")
    print("\nRESULT:", "ALL PASS" if ok else "DIAG CHECK NEEDED")


if __name__ == "__main__":
    main()
