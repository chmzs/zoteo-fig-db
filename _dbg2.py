# -*- coding: utf-8 -*-
import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

md = os.path.join("models", "granite-embedding-97m-multilingual-r2")
tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
tok.enable_truncation(512)


def make(thr):
    so = ort.SessionOptions()
    if thr:
        so.intra_op_num_threads = thr
    return ort.InferenceSession(os.path.join(md, "model_int8.onnx"), sess_options=so,
                                providers=["CPUExecutionProvider"])


def batch_run(sess, texts):
    encs = [tok.encode(t) for t in texts]
    ml = max(len(e.ids) for e in encs)
    ids = np.zeros((len(encs), ml), dtype=np.int64)
    mask = np.zeros((len(encs), ml), dtype=np.int64)
    for i, e in enumerate(encs):
        ids[i, :len(e.ids)] = e.ids
        mask[i, :len(e.ids)] = 1
    return sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]


Q = ["What is the tallest mountain in Japan?",
     "Wer hat das Lied Achy Breaky Heart geschrieben?",
     "ドイツの首都はどこですか？"]

print("A: default threads + batch3", flush=True)
o = batch_run(make(0), Q)
print("   ok", o.shape, flush=True)

print("B: intra=4 + batch3", flush=True)
s4 = make(4)
o = batch_run(s4, Q)
print("   ok", o.shape, flush=True)

print("C: intra=4 + batch100", flush=True)
o = batch_run(s4, ["Holocene temperature reconstruction proxy records"] * 100)
print("   ok", o.shape, flush=True)

print("ALL DONE", flush=True)
