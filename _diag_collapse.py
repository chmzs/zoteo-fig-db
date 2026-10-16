# -*- coding: utf-8 -*-
"""诊断：int8 vs fp32/fp16 同前向对比 + mean/CLS 双池化，定位向量坍缩原因。"""
import os
import sys
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

md = os.path.join("models", "granite-embedding-97m-multilingual-r2")
tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
tok.enable_truncation(512)

QUERIES = ["What is the tallest mountain in Japan?",
           "Wer hat das Lied Achy Breaky Heart geschrieben?",
           "ドイツの首都はどこですか？"]
PASSAGES = ["富士山は、静岡県と山梨県にまたがる活火山で、標高3776.12 mで日本最高峰の独立峰である。",
            "Achy Breaky Heart is a country song written by Don Von Tress. Originally titled Don't Tell My Heart and performed by The Marcy Brothers in 1991.",
            "Berlin ist die Hauptstadt und ein Land der Bundesrepublik Deutschland. Die Stadt ist mit rund 3,7 Millionen Einwohnern die bevölkerungsreichste Kommune Deutschlands."]


def prep(texts):
    encs = [tok.encode(t) for t in texts]
    ml = max(len(e.ids) for e in encs)
    ids = np.zeros((len(encs), ml), dtype=np.int64)
    mask = np.zeros((len(encs), ml), dtype=np.int64)
    for i, e in enumerate(encs):
        ids[i, :len(e.ids)] = e.ids
        mask[i, :len(e.ids)] = 1
    return ids, mask


def run(sess, texts, pool="cls"):
    ids, mask = prep(texts)
    out = sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
    if pool == "cls":
        v = out[:, 0, :]
    else:  # masked mean
        m = mask[:, :, None].astype(out.dtype)
        v = (out * m).sum(1) / np.clip(m.sum(1), 1, None)
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def report(name, sess, pool):
    q = run(sess, QUERIES, pool)
    p = run(sess, PASSAGES, pool)
    # 同语言两句子的余弦（应显著 <0.95，否则=坍缩）
    qn = run(sess, QUERIES[:2], pool)
    same = float(qn[0] @ qn[1])
    sim = q @ p.T
    diag = [float(sim[i, i]) for i in range(3)]
    rowmax = [int(sim[i].argmax()) for i in range(3)]
    print(f"{name} pool={pool}: same-lang-cos={same:.4f} diag={diag} rowmax={rowmax}", flush=True)
    return same < 0.9 and rowmax == [0, 1, 2] and all(d > 0.7 for d in diag)


models = [("fp32", "model.onnx"), ("fp16", "model_fp16.onnx"), ("int8", "model_int8.onnx")]
for tag, fn in models:
    path = os.path.join(md, fn)
    if not os.path.exists(path):
        print(tag, "missing", flush=True)
        continue
    try:
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        for pool in ("cls", "mean"):
            good = report(tag, sess, pool)
            print(("  >> HEALTHY " if good else "  >> BAD ") + f"{tag}/{pool}", flush=True)
    except Exception as e:
        print(tag, "FAIL", str(e)[:150], flush=True)
