# -*- coding: utf-8 -*-
import sys, os, time
print("step1 import", flush=True)
import numpy as np
import onnxruntime as ort
print("step2 ort version", ort.__version__, flush=True)
md = os.path.join("models", "granite-embedding-97m-multilingual-r2")
try:
    sess = ort.InferenceSession(os.path.join(md, "model_int8.onnx"), providers=["CPUExecutionProvider"])
    print("step3 session created", flush=True)
except Exception as e:
    print("step3 session FAILED:", str(e)[:300], flush=True)
    sys.exit(1)
from tokenizers import Tokenizer
tok = Tokenizer.from_file(os.path.join(md, "tokenizer.json"))
enc = tok.encode("What is the tallest mountain in Japan?")
ids = np.array([enc.ids], dtype=np.int64)
mask = np.ones_like(ids)
print("step4 prepared ids", flush=True)
try:
    out = sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
    print("step5 run ok", out.shape, "norm", float(np.linalg.norm(out[0,0])), flush=True)
except Exception as e:
    print("step5 run FAILED:", str(e)[:300], flush=True)
