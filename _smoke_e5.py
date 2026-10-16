# -*- coding: utf-8 -*-
"""e5-small int8 冒烟：tokenizers 加载 + mean 池化 + query/passage 前缀。"""
import os
import sys
import time
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

md = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "multilingual-e5-small")
tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
tok.enable_truncation(256)
sess = ort.InferenceSession(os.path.join(md, "model_int8.onnx"), providers=["CPUExecutionProvider"])


def vec(texts, prefix=""):
    encs = [tok.encode(prefix + t) for t in texts]
    ml = max(len(e.ids) for e in encs)
    ids = np.zeros((len(encs), ml), dtype=np.int64)
    mask = np.zeros((len(encs), ml), dtype=np.int64)
    for i, e in enumerate(encs):
        ids[i, :len(e.ids)] = e.ids
        mask[i, :len(e.ids)] = 1
    out = sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)})[0].astype(np.float32)
    m = mask[:, :, None]
    v = (out * m).sum(1) / np.clip(m.sum(1), 1e-9, None)   # masked mean
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


e = tok.encode("What is the tallest mountain in Japan?")
print("sample ids:", e.ids[:5], "...", e.ids[-1:], "unk?", tok.id_to_token(100) if 100 in e.ids else "-", flush=True)

q = vec(["全新世温度重建", "Holocene temperature reconstruction", "Unrelated dust cycle talk"], prefix="query: ")
p = vec(["Holocene temperature reconstruction of the past 6000 years",
         "Mid-latitude dust cycle and aeolian deposition records",
         "全新世中期温度记录"], prefix="passage: ")
print("cos zh->en_related=%.4f  zh->unrelated=%.4f  margin=%.4f" % (q[0] @ p[0], q[0] @ p[1], q[0] @ p[0] - q[0] @ p[1]), flush=True)
print("cos zh->zh=%.4f  en_selfpair=%.4f" % (q[0] @ p[2], q[1] @ p[0]), flush=True)
t0 = time.time(); vec(["x" for _ in range(100)], prefix="query: ")
print("throughput: %.0f texts/s" % (100 / (time.time() - t0)), flush=True)
