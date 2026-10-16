# -*- coding: utf-8 -*-
"""
Zotero GeoFigure Engine (fig_db)
- Robust multi-publisher Figure & Caption Alignment
  (Elsevier, Nature, AAAS/Science, AGU/Wiley, Springer, EGU, Chinese Journals)
- Precise bounding box detection via vector drawings + raster images (Zero text pollution)
- Bilingual Caption Merging (Chinese '图 N' + English 'Fig. N')
- High-Quality WebP (quality=85) Storage
- e5-small INT8 Embedding & SQLite FTS5 Hybrid Search
"""

import os
import re
import time
import io
import sqlite3
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
import onnxruntime as ort
from adapters import get_adapter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models", "multilingual-e5-small")
DB_PATH = os.path.join(BASE_DIR, "zotero-figures.sqlite")
IMAGE_DIR = os.path.join(BASE_DIR, "cache", "figures")
CURRENT_EXTRACTOR_VERSION = "1.9"   # 全局版本戳（figures.extractor_version 唯一来源）
WEBP_QUALITY = 72
MAX_FULL_SIDE = 1600
THUMB_MAX_SIDE = 480
os.makedirs(IMAGE_DIR, exist_ok=True)

# ---- 期刊通行简称（Zotero journalAbbreviation 缺值时的地学界通用兜底表）----
LT_ABBREVIATIONS = {
    "science advances": "Sci. Adv.", "quaternary science reviews": "Quat. Sci. Rev.",
    "geophysical research letters": "Geophys. Res. Lett.",
    "nature communications": "Nat. Commun.", "nature geoscience": "Nat. Geosci.",
    "nature climate change": "Nat. Clim. Chang.",
    "nature ecology & evolution": "Nat. Ecol. Evol.", "nature sustainability": "Nat. Sustain.",
    "earth and planetary science letters": "Earth Planet. Sci. Lett.",
    "earth-science reviews": "Earth-Sci. Rev.", "quaternary international": "Quat. Int.",
    "global and planetary change": "Global Planet. Change", "global and planetary change": "Global Planet. Change",
    "journal of hydrology": "J. Hydrol.", "water research": "Water Res.",
    "remote sensing of environment": "Remote Sens. Environ.",
    "palaeogeography, palaeoclimatology, palaeoecology": "Palaeogeogr. Palaeoclimatol. Palaeoecol.",
    "climate dynamics": "Clim. Dyn.", "climate of the past": "Clim. Past",
    "international journal of climatology": "Int. J. Climatol.",
    "international journal of digital earth": "Int. J. Digit. Earth",
    "methods in ecology and evolution": "Methods Ecol. Evol.",
    "proceedings of the national academy of sciences": "PNAS",
    "water resources research": "Water Resour. Res.", "reviews of geophysics": "Rev. Geophysics",
    "geochemistry, geophysics, geosystems": "Geochem. Geophys. Geosyst.",
    "geochimica et cosmochimica acta": "Geochim. Cosmochim. Acta",
    "agricultural and forest meteorology": "Agric. For. Meteorol.",
    "isprs journal of photogrammetry and remote sensing": "ISPRS J. Photogramm. Remote Sens.",
    "advances in water resources": "Adv. Water Resour.",
    "journal of advances in modeling earth systems": "J. Adv. Model. Earth Syst.",
    "ecography": "Ecography", "catena": "CATENA", "geology": "Geology",
    "nature": "Nature", "science": "Science", "tectonics": "Tectonics",
    "the holocene": "Holocene", "earth's future": "Earth's Future", "one earth": "One Earth",
}
_SKIP_WORDS = {"of", "and", "the", "in", "on", "for", "a", "an", "de", "et", "la", "le"}


def journal_abbr_str(journal):
    """期刊通行简称：先查定制表（覆盖地学主流刊），否则 ISO-4 式首字母兜底；中文刊保持原名。"""
    if not journal or not journal.strip():
        return ""
    j = journal.strip()
    if re.search(r"[\u4e00-\u9fff]", j):
        return j
    key = re.sub(r"[^a-z0-9&,.\- ]", "", j.lower()).strip()
    if key in LT_ABBREVIATIONS:
        return LT_ABBREVIATIONS[key]
    words = [w for w in re.split(r"[\s\-:,]+", j) if w]
    out = []
    content = [w for w in words if w.lower().strip(".,") not in _SKIP_WORDS and len(w.strip("., ")) > 1]
    if len(content) == 1:
        return j  # 单词刊（Oryx/Nature/Geology 类）保持全名
    for idx, w in enumerate(words):
        wl = w.lower().strip(".,")
        if not wl or (idx > 0 and wl in _SKIP_WORDS):
            continue
        if len(wl) <= 2 and idx > 0:
            continue
        if wl in ("journal", "journal"):
            out.append("J.")
        elif wl.endswith("ology"):
            out.append(wl[:4] + "y.") if wl[:4].isalpha() else out.append(w[0] + ".")
        elif wl.endswith("ics"):
            out.append(wl[:-3] + "cs." if len(wl) > 6 else w[0] + ".")
        elif wl.endswith("y"):
            out.append(wl[:-1] + "y." if len(wl) > 4 else w[0] + ".")
        else:
            out.append(w[0].upper() + ".")
        if len(out) >= 4:
            break
    return " ".join(out) if out else j


def _display_authors(first, last=None):
    """卡片显示：第一作者全名（名 姓），单人时即其本人"""
    return (first or last or "").strip()


def zot_abbr_plausible(journal, abbr):
    """校验 Zotero journalAbbreviation 字段值是否与刊名对得上。
    拦截元数据错配遗留的脏值（如 'REMOTE SENS-BASEL' 挂在 Earth-Science Reviews 下）。"""
    a = (abbr or "").strip()
    j = (journal or "").strip()
    if not a or not j:
        return False
    if re.search(r"[\u4e00-\u9fff]", j) or re.search(r"[\u4e00-\u9fff]", a):
        return True  # 中文刊/中文简称不做缩写校验
    jw = [w for w in re.split(r"[^A-Za-z0-9]+", j) if w and len(w) > 1 and w.lower() not in _SKIP_WORDS]
    if not jw:
        return True
    joined = re.sub(r"[.\-,]+", " ", a).split()
    joined = "".join(joined).upper()
    if not joined:
        return False
    initials = "".join(w[0].upper() for w in jw)
    # 首字母缩略风格（ESR / GRL / JAMES）：须为刊名首字母序列的子序列且以首字母开头
    if joined.isalpha() and len(joined) <= len(initials) and joined[0] == initials[0]:
        it = iter(initials)
        if all(c in it for c in joined[1:]):
            return True
    # 词缩写风格（Sci. Bull. / Nat. Commun. / Holo.）：token 依序为刊名词的前缀
    toks = [t for t in re.sub(r"[.,]+", " ", a).split() if t]
    wi = 0
    matched_any = False
    for t in toks:
        base = t.lower()
        hit = None
        for k in range(wi, len(jw)):
            wl = jw[k].lower()
            if wl == base or (len(base) >= 3 and wl.startswith(base)):
                hit = k
                break
        if hit is None:
            return False
        wi = hit + 1
        matched_any = True
    return matched_any


def resolve_abbr(journal, zot_abbr=""):
    """简称优先级：Zotero 字段（校验合法，与用户文库/管理端一致）> 定制表 > 通用兜底。"""
    j = (journal or "").strip()
    if not j:
        return (zot_abbr or "").strip()
    if re.search(r"[\u4e00-\u9fff]", j):
        return j
    key = re.sub(r"[^a-z0-9&,.\- ]", "", j.lower()).strip()
    z = (zot_abbr or "").strip()
    if z and z.lower() != key and zot_abbr_plausible(j, z):
        return z
    if key in LT_ABBREVIATIONS:
        return LT_ABBREVIATIONS[key]
    return journal_abbr_str(j)


def _so():
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    return so


class Encoder:
    """multilingual-e5-small INT8（118MB，MIT）：mean pooling + L2；query/passage 前缀。
    中英文/跨语言统一空间；换模型只改本类与 MODEL_DIR，调用点名字稳定。"""

    def __init__(self, model_dir=MODEL_DIR):
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(256)
        self.session = ort.InferenceSession(
            os.path.join(model_dir, "model_int8.onnx"),
            sess_options=_so(),
            providers=["CPUExecutionProvider"],
        )

    def _vec(self, text, prefix):
        if not text or not text.strip():
            return np.zeros(384, dtype=np.float32)
        enc = self.tok.encode(prefix + text)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.ones_like(ids)
        outputs = self.session.run(None, {
            "input_ids": ids,
            "attention_mask": mask,
            "token_type_ids": np.zeros_like(ids),
        })
        m = mask[..., np.newaxis].astype(np.float32)
        embedding = (outputs[0] * m).sum(axis=1) / np.clip(m.sum(axis=1), a_min=1e-9, a_max=None)
        norm = np.linalg.norm(embedding, axis=1, keepdims=True)
        if norm[0, 0] > 0:
            embedding = embedding / norm
        return embedding[0].astype(np.float32)

    def encode(self, text):
        return self._vec(text, "passage: ")

    def encode_query(self, text):
        return self._vec(text, "query: ")



class FigureDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_conn(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def _init_db(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS figures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT,
            att_key TEXT,
            title TEXT,
            year INTEGER,
            journal TEXT,
            journal_abbr TEXT,
            authors TEXT,
            fig_no TEXT,
            caption TEXT,
            context_text TEXT,
            image_path TEXT,
            page_no INTEGER,
            embedding BLOB,
            indexed_at INTEGER,
            extractor_version TEXT DEFAULT '1.2',
            UNIQUE(item_key, fig_no)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_item_key ON figures(item_key);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal ON figures(journal);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_year ON figures(year);")

        # 迁移：期刊简称列（Zotero journalAbbreviation 字段 + 地学通行缩写兜底）
        _cols = [c[1] for c in cursor.execute("PRAGMA table_info(figures);").fetchall()]
        if "journal_abbr" not in _cols:
            cursor.execute("ALTER TABLE figures ADD COLUMN journal_abbr TEXT DEFAULT '';")
        if "authors" not in _cols:
            cursor.execute("ALTER TABLE figures ADD COLUMN authors TEXT DEFAULT '';")

        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_figures USING fts5(
            fig_no,
            caption,
            title,
            journal,
            context_text,
            content='figures',
            content_rowid='id'
        );
        """)
        conn.commit()
        conn.close()

    def insert_figure(self, record):
        conn = self.get_conn()
        cursor = conn.cursor()
        emb_blob = record["embedding"].tobytes() if record.get("embedding") is not None else None

        cursor.execute("""
        INSERT OR REPLACE INTO figures (
            item_key, att_key, title, year, journal, journal_abbr, authors, fig_no, caption, 
            context_text, image_path, page_no, embedding, 
            indexed_at, extractor_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            record["item_key"],
            record.get("att_key", ""),
            record.get("title", ""),
            record.get("year", 0),
            record.get("journal", ""),
            record.get("journal_abbr", ""),
            record.get("authors", ""),
            record["fig_no"],
            record["caption"],
            record.get("context_text", ""),
            record["image_path"],
            record.get("page_no", 1),
            emb_blob,
            int(time.time()),
            CURRENT_EXTRACTOR_VERSION  # v2.0: 全局版本戳单点（勿硬编码）,
        ))
        row_id = cursor.lastrowid
        cursor.execute("""
        INSERT OR REPLACE INTO fts_figures (rowid, fig_no, caption, title, journal, context_text)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (
            row_id,
            record["fig_no"],
            record["caption"],
            record.get("title", ""),
            record.get("journal", ""),
            record.get("context_text", ""),
        ))
        conn.commit()
        conn.close()
        return row_id

    def exists_item(self, item_key):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM figures WHERE item_key = ?", (item_key,))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0

    def get_stats(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*), count(DISTINCT item_key) FROM figures")
        total_figs, total_items = cursor.fetchone()
        conn.close()
        return {"total_figures": total_figs, "total_papers": total_items}


class FigureExtractor:
    def __init__(self, output_dir=IMAGE_DIR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _save_full(self, im, webp_path):
        """原图封顶 1600px（视觉模型有效上限~1568px，再高对模型与肉眼灯箱均无增益）"""
        if max(im.size) > MAX_FULL_SIDE:
            r = MAX_FULL_SIDE / max(im.size)
            im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
        im.save(webp_path, "WEBP", quality=WEBP_QUALITY, method=4)

    def _save_thumb(self, im, webp_path):
        """480px 缩略图：画廊卡片只加载 ~17KB，点开灯箱才加载原图"""
        try:
            t = im.copy()
            t.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            t.save(webp_path[:-5] + ".thumb.webp", "WEBP", quality=WEBP_QUALITY, method=4)
        except Exception:
            pass

    def extract_from_pdf(self, pdf_path, item_key, att_key="", title="", year=0, journal=""):
        if not os.path.exists(pdf_path):
            return []

        try:
            doc = fitz.open(pdf_path)
            max_pages = min(len(doc), 120)
            adapter = get_adapter(journal, doc)
        except Exception as e:
            print(f"Error opening PDF {pdf_path}: {e}")
            return []

        results = []

        for page_idx in range(max_pages):
            page = doc[page_idx]
            captions_on_page = adapter.find_captions(page, page_idx)
            if not captions_on_page:
                continue

            # 1. Collect raster image METADATA only (no full decode; decode only the matched one later)
            infos = page.get_image_info(xrefs=True)
            valid_images = []
            seen_xref = set()
            for info in infos:
                xref = info.get("xref")
                if xref is None or xref in seen_xref:
                    continue
                w, h = info.get("width", 0), info.get("height", 0)
                if w >= 200 and h >= 160:
                    seen_xref.add(xref)
                    bb = info.get("bbox")
                    valid_images.append({
                        "xref": xref,
                        "w": w,
                        "h": h,
                        "rect": fitz.Rect(bb) if bb else None,
                    })

            # 2. Collect all vector drawings on this page (graceful degrade on MuPDF
            # "nested graphics states" style errors: raster evidence still works)
            try:
                page_drawings = page.get_drawings()
            except Exception:
                page_drawings = []

            for cap in captions_on_page:
                # 书目录点线行（"图21 xxx 41 ......"）不可能是真题注：≥4 连点即拒
                if re.search(r"[.…·]{4,}", cap["caption"]):
                    continue
                fig_no_clean = re.sub(r"[^\w\d]", "_", cap["fig_no"])
                webp_filename = f"{item_key}_{fig_no_clean}_p{page_idx+1}.webp"
                webp_path = os.path.join(self.output_dir, webp_filename)
                cap_rect = cap["rect"]

                clip_rect, matched_raster = adapter.locate_figure_box(
                    page=page,
                    cap_rect=cap_rect,
                    valid_images=valid_images,
                    page_drawings=page_drawings,
                    text_spans=None,
                    all_captions=captions_on_page,
                )

                saved = False
                if matched_raster:
                    try:
                        raw_bytes = doc.extract_image(matched_raster["xref"])["image"]
                        im = Image.open(io.BytesIO(raw_bytes))
                        if im.mode in ("RGBA", "P"):
                            im = im.convert("RGB")
                        self._save_full(im, webp_path)
                        self._save_thumb(im, webp_path)
                        saved = True
                    except Exception:
                        pass

                if not saved and clip_rect and clip_rect.height >= 80 and clip_rect.width >= 80:
                    try:
                        pix = page.get_pixmap(clip=clip_rect, dpi=200)
                        im = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        self._save_full(im, webp_path)
                        self._save_thumb(im, webp_path)
                        saved = True
                    except Exception:
                        pass

                thumb_name = ""
                if saved:
                    candidate = webp_path[:-5] + ".thumb.webp"
                    if os.path.exists(candidate):
                        thumb_name = os.path.basename(candidate)
                    results.append({
                        "item_key": item_key,
                        "att_key": att_key,
                        "title": title,
                        "year": year,
                        "journal": journal,
                        "fig_no": cap["fig_no"],
                        "caption": cap["caption"],
                        "context_text": "",
                        "image_path": webp_path,
                        "thumb_name": thumb_name,
                        "page_no": page_idx + 1,
                    })

        doc.close()
        return results


class FigureSearcher:
    """Hybrid two-stage search with numpy matrix cache for large libraries (10k+ figures).

    Stage 1: e5 cosine similarity via single BLAS matmul over cached matrix
             + FTS5 keyword recall (OR of query terms) to catch exact phrases.
    Stage 2: Keyword-bonus reranking only on the merged candidate set (~top 400).
    """

    def __init__(self, db_path=DB_PATH, model_dir=MODEL_DIR):
        self.db = FigureDB(db_path)
        self.encoder = Encoder(model_dir)
        self._M = None            # (N, 384) float32 matrix（冷启动时 mmap 加载）
        self._metas = None        # list of dicts
        self._id2idx = None       # figures.id -> row index
        self._sig = None          # cache signature
        self._cache_npy = os.path.join(BASE_DIR, "cache", "embed_matrix.npy")
        self._cache_pkl = os.path.join(BASE_DIR, "cache", "embed_meta.pkl")

    def _dump_cache(self):
        """落盘：npy 供 mmap 快速重载，pkl 存签名与元数据"""
        try:
            import pickle
            if self._M is not None and len(self._M):
                np.save(self._cache_npy, np.ascontiguousarray(self._M))
                with open(self._cache_pkl, "wb") as f:
                    pickle.dump({"sig": self._sig, "metas": self._metas}, f, protocol=4)
        except Exception:
            pass

    def _try_load_disk_cache(self, sig):
        try:
            import pickle
            if not (os.path.exists(self._cache_npy) and os.path.exists(self._cache_pkl)):
                return False
            with open(self._cache_pkl, "rb") as f:
                blob = pickle.load(f)
            if blob.get("sig") != sig:
                return False
            self._M = np.load(self._cache_npy, mmap_mode="r")
            self._metas = blob["metas"]
            self._id2idx = {m["id"]: i for i, m in enumerate(self._metas)}
            self._sig = sig
            return True
        except Exception:
            return False

    def _signature(self):
        conn = self.db.get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(MAX(indexed_at),0), COALESCE(MAX(id),0) FROM figures")
        sig = cur.fetchone()
        conn.close()
        return sig

    def _load_row(self, r):
        (r_id, item_key, att_key, title, year, journal, journal_abbr, authors, fig_no,
         caption, ctx, img_path, page_no, emb_blob) = r
        emb = np.frombuffer(emb_blob, dtype=np.float32) if emb_blob else np.zeros(384, dtype=np.float32)
        thumb_name = ""
        if img_path and img_path.lower().endswith(".webp"):
            cand = img_path[:-5] + ".thumb.webp"
            if os.path.exists(cand):
                thumb_name = os.path.basename(cand)
        meta = {
            "id": r_id,
            "item_key": item_key,
            "att_key": att_key,
            "title": title,
            "year": year,
            "journal": journal,
            "journal_abbr": journal_abbr or "",
            "authors": authors or "",
            "fig_no": fig_no,
            "caption": caption,
            "context_text": ctx,
            "image_path": img_path,
            "thumb_name": thumb_name,
            "page_no": page_no,
            "_cap_l": (caption or "").lower(),
            "_title_l": (title or "").lower(),
            "_fig_l": (fig_no or "").lower(),
            "_dedup": (re.sub(r"\W+", "", (title or "").lower())[:30],
                       re.sub(r"\W+", "", (fig_no or "").lower())),
        }
        return emb, meta

    _COLS = ("SELECT id, item_key, att_key, title, year, journal, journal_abbr, authors, fig_no, caption, "
             "context_text, image_path, page_no, embedding FROM figures")

    def _ensure_cache(self):
        sig = self._signature()
        if self._M is not None and self._sig == sig:
            return

        # 冷启动：优先 mmap 磁盘缓存（重启后零重建）
        if self._M is None and self._try_load_disk_cache(sig):
            return

        # 快速路径：纯增量追加（count 增量 == max_id 增量，无删除/无 REPLACE 空洞）
        if (self._M is not None and len(self._metas) > 0
                and sig[2] > self._sig[2]
                and (sig[0] - self._sig[0]) == (sig[2] - self._sig[2])):
            conn = self.db.get_conn()
            cur = conn.cursor()
            cur.execute(self._COLS + " WHERE id > ? ORDER BY id", (self._sig[2],))
            rows = cur.fetchall()
            conn.close()
            if rows:
                new_mats = []
                for r in rows:
                    emb, meta = self._load_row(r)
                    if not meta.get("journal_abbr"):
                        meta["journal_abbr"] = journal_abbr_str(meta.get("journal", ""))
                    new_mats.append(emb)
                    self._id2idx[meta["id"]] = len(self._metas)
                    self._metas.append(meta)
                self._M = np.vstack([np.asarray(self._M), np.stack(new_mats)])
            self._sig = sig
            self._dump_cache()
            return

        # 全量重建
        conn = self.db.get_conn()
        cur = conn.cursor()
        cur.execute(self._COLS)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            self._M = np.zeros((0, 384), dtype=np.float32)
            self._metas, self._id2idx, self._sig = [], {}, sig
            return

        mats = []
        metas = []
        id2idx = {}
        for i, r in enumerate(rows):
            emb, meta = self._load_row(r)
            if not meta.get("journal_abbr"):
                meta["journal_abbr"] = journal_abbr_str(meta.get("journal", ""))
            mats.append(emb)
            metas.append(meta)
            id2idx[meta["id"]] = i

        self._M = np.stack(mats).astype(np.float32, copy=False)
        self._metas = metas
        self._id2idx = id2idx
        self._sig = sig
        self._dump_cache()

    def _fts_candidates(self, query):
        """FTS5 OR-recall: return list of figures.id hits (or [] on failure)."""
        terms = re.findall(r"[\w\u4e00-\u9fff]+", query)
        if not terms:
            return []
        terms = terms[:12]
        match = " OR ".join(f'"{t}"' for t in terms)
        try:
            conn = self.db.get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT rowid FROM fts_figures WHERE fts_figures MATCH ? LIMIT 600", (match,)
            )
            ids = [row[0] for row in cur.fetchall()]
            conn.close()
            return ids
        except Exception:
            return []

    def search(self, query, top_k=20, journal_filter=None, year_min=None, year_max=None):
        query = query.strip()
        if not query:
            return []

        self._ensure_cache()
        if self._M is None or len(self._metas) == 0:
            return []

        from notes_index import make_wikilink, clean_wikilink_alias

        q_emb = self.encoder.encode_query(query)
        sims = self._M @ q_emb

        n = len(self._metas)
        pool = int(max(200, top_k * 10))
        if n <= pool:
            cand_idx = list(range(n))
        else:
            cand_idx = np.argpartition(-sims, pool)[:pool].tolist()

        fts_ids = self._fts_candidates(query)
        if fts_ids:
            cand_idx.extend(self._id2idx[i] for i in fts_ids if i in self._id2idx)

        jf = journal_filter.lower() if journal_filter else None
        ymin = int(year_min) if year_min else None
        ymax = int(year_max) if year_max else None

        q_lower = query.lower()
        scored = []
        seen_cand = set()
        for i in cand_idx:
            if i in seen_cand:
                continue
            seen_cand.add(i)
            m = self._metas[i]
            if jf and jf not in (m["journal"] or "").lower():
                continue
            if ymin is not None and (m["year"] or 0) < ymin:
                continue
            if ymax is not None and (m["year"] or 9999) > ymax:
                continue

            sim = float(sims[i])
            bonus = 0.0
            if q_lower in m["_cap_l"]:
                bonus += 0.15
            if q_lower in m["_title_l"]:
                bonus += 0.10
            if q_lower in m["_fig_l"]:
                bonus += 0.20
            scored.append((sim + bonus, sim, i))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen = set()
        for final_score, sim, i in scored:
            m = self._metas[i]
            if m["_dedup"] in seen:
                continue
            seen.add(m["_dedup"])
            wikilink, link_kind = make_wikilink(m["item_key"], m["title"])
            wikilink = clean_wikilink_alias(wikilink, m.get("journal_abbr") or "")
            authors_str = m.get("authors", "") or _display_authors(m.get("author_first", ""), m.get("author_last", ""))
            results.append({
                "id": m["id"],
                "item_key": m["item_key"],
                "att_key": m["att_key"],
                "title": m["title"],
                "year": m["year"],
                "journal": m["journal"],
                "journal_abbr": m.get("journal_abbr") or journal_abbr_str(m["journal"]),
                "authors": authors_str,
                "fig_no": m["fig_no"],
                "caption": m["caption"],
                "context_text": m["context_text"],
                "image_path": m["image_path"],
                "thumb_name": m["thumb_name"],
                "page_no": m["page_no"],
                "wikilink": wikilink,
                "link_kind": link_kind,
                "score": round(final_score, 4),
                "semantic_sim": round(sim, 4),
            })
            if len(results) >= top_k:
                break

        return results
