# -*- coding: utf-8 -*-
"""终审：Granite 与 e5 在同一 20 查询上的 top-5 互相印证度。"""
import os
import sys
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from engine import FigureDB

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


def load_matrix(mat_f, ids_f):
    M = np.load(os.path.join(BASE, "cache", mat_f))
    ids = np.load(os.path.join(BASE, "cache", ids_f))
    return M, ids


class Enc:
    def __init__(self, md, file, mode):
        self.tok = Tokenizer.from_file(os.path.join(BASE, "models", md, "tokenizer.json"))
        self.tok.enable_truncation(256)
        self.sess = ort.InferenceSession(os.path.join(BASE, "models", md, file),
                                         providers=["CPUExecutionProvider"])
        self.mode = mode  # 'cls' or 'mean'

    def vec(self, texts, prefix=""):
        encs = [self.tok.encode(prefix + t) for t in texts]
        ml = max(len(e.ids) for e in encs)
        ids = np.zeros((len(encs), ml), dtype=np.int64)
        mask = np.zeros((len(encs), ml), dtype=np.int64)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        out = self.sess.run(None, {"input_ids": ids, "attention_mask": mask,
                                   "token_type_ids": np.zeros_like(ids)})[0].astype(np.float32) \
            if self.mode == "mean" else \
            self.sess.run(None, {"input_ids": ids, "attention_mask": mask})[0].astype(np.float32)
        v = out[:, 0, :] if self.mode == "cls" else \
            (out * mask[:, :, None]).sum(1) / np.clip(mask.sum(1), 1, None)
        return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-9, None)


def main():
    G, ids = load_matrix("ab_granite_mat.npy", "ab_granite_ids.npy")
    E, _ = load_matrix("ab_e5_mat.npy", "ab_e5_ids.npy")
    assert np.array_equal(ids, np.load(os.path.join(BASE, "cache", "ab_e5_ids.npy")))

    conn = FigureDB().get_conn()
    meta = {r[0]: (r[1], r[2]) for r in
            conn.execute("SELECT id, journal, fig_no FROM figures")}
    conn.close()

    gq = Enc("granite-embedding-97m-multilingual-r2", "model.onnx", "cls").vec(QUERIES)
    eq = Enc("multilingual-e5-small", "model_int8.onnx", "mean").vec(QUERIES, prefix="query: ")

    agree = []
    for i in range(len(QUERIES)):
        gt = set(ids[np.argsort(-(G @ gq[i]))[:5]])
        et = set(ids[np.argsort(-(E @ eq[i]))[:5]])
        agree.append(len(gt & et))
    zh = agree[:10]
    en = agree[10:]
    print("中文组 Granite∩e5 top5 一致数:", zh, f"均值 {sum(zh)/10:.1f}/5")
    print("英文组 Granite∩e5 top5 一致数:", en, f"均值 {sum(en)/10:.1f}/5")
    print("总一致率:", f"{sum(agree)/100*100:.0f}%")


if __name__ == "__main__":
    main()
