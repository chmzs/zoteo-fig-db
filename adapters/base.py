"""
Base Publisher Adapter for Zotero GeoFigure Engine
Defines the interface for publisher-specific PDF layout adapters.
"""

import re

import fitz
import numpy as np


class BaseAdapter:
    """Base class for all publisher-specific PDF layout adapters."""
    name = "base"
    # 面板级切分开关：仅多联图重灾区且有图形证据链可守的家族开启（elsevier/agu/nature）。
    # chinese/generic 双栏混排易误切 → 只出整图，等误切率数据说话再扩。
    panel_split = False
    # 独立成 span 的单字母面板标签："(a)" "a" "(b)." 等
    PANEL_LABEL_RE = re.compile(r"^[\[\(\{]?\s*([a-z])\s*[\]\)\}]?[\.:]?$")

    def match(self, journal: str, doc: fitz.Document) -> bool:
        """Return True if this adapter handles the journal/publisher."""
        return False

    def find_captions(self, page: fitz.Page, page_idx: int) -> list:
        """
        Extract caption text blocks from a page.
        Returns: list of dicts: {'fig_no': str, 'fig_num': str, 'caption': str, 'rect': fitz.Rect}
        """
        blocks = page.get_text("blocks")
        captions = []
        fig_pattern = re.compile(
            r"^((?:(?:Supplementary|Supplemental|Appendix|Extended\s+Data)\s+)?(?:Figure\s+(S?\d+[a-zA-Z]?)|Fig\.\s*(S?\d+[a-zA-Z]?)|图\s*(S?\d+[a-zA-Z]?)|附图\s*(S?\d+[a-zA-Z]?))[\.:\s|])",
            re.IGNORECASE,
        )

        matched_idx = set()
        for bi, b in enumerate(blocks):
            if b[6] == 0:  # text
                txt = b[4].strip()
                if re.match(r"^(Table|Tab\.|表)\b", txt, re.IGNORECASE):
                    continue
                m = fig_pattern.search(txt)
                if m:
                    matched_idx.add(bi)
                    matched_str = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(".:|").strip()
                    num_m = re.search(r"\d+[a-zA-Z]?", matched_str)
                    fig_num = num_m.group(0).lower() if num_m else matched_str
                    caption_text = txt.replace("\n", " ").strip()
                    captions.append({
                        "fig_no": matched_str,
                        "fig_num": fig_num,
                        "caption": caption_text,
                        "rect": fitz.Rect(b[0], b[1], b[2], b[3]),
                    })

        # 行级救援（v1.7）：块首非题注、但块内行首为 "Figure N <长句>"（Annual Reviews 等
        # 题注嵌在图例之后）。假阳防线：真题注上方必有图形，locate 的图形证据门会拒绝
        # 上方为正文的段首引用（"Figure 2 shows..."）。
        rescue_pat = re.compile(
            r"^(Figure|Fig\.?)\s+(S?\d+[a-zA-Z]?)\s+([A-Z0-9(一-鿿].{24,})$")
        label_pat = re.compile(r"^(Figure|Fig\.?)\s+(S?\d+[a-zA-Z]?)[:.]?$", re.IGNORECASE)
        line_rects = None
        for bi, b in enumerate(blocks):
            if b[6] != 0 or bi in matched_idx:
                continue
            lines = [l.strip() for l in b[4].splitlines()]
            for li, ln in enumerate(lines):
                rm = rescue_pat.match(ln)
                body = ln
                if not rm:
                    lm = label_pat.match(ln)
                    if not lm:
                        continue
                    nxt = " ".join(x for x in lines[li + 1:li + 3] if x).strip()
                    if len(nxt) < 25:
                        # 纯标签独立成块（Annual Reviews）：向后借 1-2 个文本块首行
                        for nb in blocks[bi + 1:bi + 3]:
                            if nb[6] != 0:
                                continue
                            s = nb[4].strip().replace("\n", " ")
                            if re.match(r"^(Table|Tab\.|表)\b", s, re.IGNORECASE):
                                continue
                            seg = " ".join(x.strip() for x in s.splitlines()[:1])[:200]
                            if len(seg) >= 25 and re.match(r"^[A-Z0-9(一-鿿]", seg):
                                nxt = (nxt + " " + seg).strip() if nxt else seg
                            if len(nxt) >= 25:
                                break
                    if len(nxt) < 25 or not re.match(r"^[A-Z0-9(一-鿿]", nxt):
                        continue
                    rm = lm
                    body = f"{ln} {nxt}"
                if re.match(r"^(Table|Tab\.|表)\b", body, re.IGNORECASE):
                    continue
                if line_rects is None:
                    line_rects = self._page_line_rects(page)
                rect = line_rects.get(re.sub(r"\s+", " ", ln)[:80])
                if rect is None:
                    continue
                captions.append({
                    "fig_no": f"{rm.group(1)} {rm.group(2)}".strip(),
                    "fig_num": rm.group(2).lower(),
                    "caption": re.sub(r"\s+", " ", body),
                    "rect": rect,
                })
                break
        return captions

    @staticmethod
    def _page_line_rects(page):
        out = {}
        try:
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    t = "".join(s.get("text", "") for s in line.get("spans", []))
                    key = re.sub(r"\s+", " ", t).strip()
                    if len(key) > 6 and key not in out:
                        bb = line.get("bbox")
                        if bb:
                            out[key[:80]] = fitz.Rect(bb)
        except Exception:
            pass
        return out

    def locate_figure_box(self, page: fitz.Page, cap_rect: fitz.Rect, valid_images: list,
                          page_drawings: list, text_spans: list = None,
                          all_captions: list = None) -> tuple:
        """定位题注上方的图形区域。返回 (clip Rect 或 None, 命中位图 dict 或 None)。

        原则：宁宽勿裁，但绝不盲裁。
        - 位图证据优先（原始字节最高保真）；
        - 矢量图取 路径∪位图∪紧邻文本标注 并集（刻度数字/单位/(a)(b) 不被裁掉）；
        - 题注上方无任何图形证据 → 拒绝（杀掉"正文交叉引用被当题注"的假图卡）。
        """
        page_rect = page.rect
        is_left = cap_rect.x1 < page_rect.width * 0.55
        is_right = cap_rect.x0 > page_rect.width * 0.45
        is_full = cap_rect.width > page_rect.width * 0.55

        if is_left and not is_full:
            cx0, cx1 = 35.0, page_rect.width * 0.52
        elif is_right and not is_full:
            cx0, cx1 = page_rect.width * 0.48, page_rect.width - 35.0
        else:
            cx0, cx1 = 35.0, page_rect.width - 35.0

        # ---- 主路径：图形在题注上方（绝大多数出版商）----
        # 带顶：从同栏上一条题注底截断（单栏多图页防止把上一张图吞进本张并集）
        band_top = 45.0
        if all_captions:
            for c2 in all_captions:
                r2 = c2["rect"]
                if r2 is not cap_rect and r2.y1 <= cap_rect.y0 - 5 and r2.x1 > cx0 and r2.x0 < cx1:
                    band_top = max(band_top, r2.y1 + 3)
        band = fitz.Rect(cx0, band_top, cx1, cap_rect.y0)
        band_imgs, band_dr = [], []
        if band.height >= 60:
            band_imgs = [vi for vi in valid_images
                         if vi["rect"] and vi["rect"].intersects(band) and vi["rect"].y1 <= cap_rect.y0 + 15]
            band_dr = [d["rect"] for d in page_drawings
                       if d["rect"].y1 <= cap_rect.y0 + 12 and d["rect"].y0 >= 40 and d["rect"].intersects(band)
                       and d["rect"].y1 > 64]  # 页眉带(logo/下划线/装饰)无条件排除

            # 单幅位图且无矢量叠加、且完整落在带内 → 直接抽原始字节（最常见，最高保真）
            # §八③: 越过带顶 = 与上邻图共享复合位图/跨带残留，禁原始直取，改带内裁切
            if (len(band_imgs) == 1 and not band_dr
                    and band_imgs[0]["rect"].y0 >= band.y0 - 2.0):
                return None, band_imgs[0]

        # §八③: 证据矩形一律 ∩band 后再并（band 外部分属上邻图，不得吞入本图裁框）
        parts = [vi["rect"] & band for vi in band_imgs] + band_dr
        if parts:
            u = parts[0]
            for r in parts[1:]:
                u = u | r
            u = self._merge_spans(page, u, text_spans, 40.0, cap_rect.y0 - 2, 14.0, 10.0)
            clip = fitz.Rect(
                max(25, u.x0 - 6),
                max(64, u.y0 - 6),   # 页眉硬地板：期刊页眉带 <62pt，簇顶一律不得升入页眉区
                min(page_rect.width - 25, u.x1 + 6),
                min(cap_rect.y0 - 2, u.y1 + 6),
            )
            # §八③: 终检不变式 clip ⊆ band——merge_spans 允许标注上探 14pt，
            # 叠栏多图页会把上邻图的轴刻度并入 → pad 后统一回裁，越带部分判归上邻图
            if band.height >= 60:
                clip = clip & band
            if clip.height < 60 or clip.width < 80:
                return fitz.Rect(band.x0, max(64, band.y0), band.x1, band.y1), None
            return clip, None

        # ---- 回退路径：题注在图上方（Wiley Accepted Article 等手稿式排版）----
        # 题注块高 <220pt：防"图注并入正文长块"的假题注从下方误捕
        if (cap_rect.y1 - cap_rect.y0) < 220:
            clip_b, raster_b = self._figure_below_caption(
                page, cap_rect, valid_images, page_drawings, text_spans, cx0, cx1)
            if clip_b is not None or raster_b is not None:
                return clip_b, raster_b

        # ---- 回退路径：题注与图左右并排（老刊侧置图注版式；限窄题注块）----
        if cap_rect.width < page_rect.width * 0.5:
            clip_s, raster_s = self._figure_beside_caption(
                page, cap_rect, valid_images, page_drawings, text_spans)
            if clip_s is not None or raster_s is not None:
                return clip_s, raster_s

        # 两个方向都没有图形证据：假题注，拒绝，绝不盲裁
        return None, None

    # ---------------- 位图内缝切分（v2.1 路线 B：复合位图的面板字母烧死在像素里） ----------------
    # 实测（2026-10-19, 41 篇/323 父图）：elsevier 文本层面板标签仅 1.8%，77% 父图为位图主导；
    # nature 反之（标签 44.4%、位图主导 17%）。故两路线互补：
    #   路线 A _panel_labels+网格 —— 只对矢量标注版面有效；
    #   路线 B 本函数 —— 复合位图内部相对极小值缝 + 题注声明面板数做语义锚。

    RASTER_WORK_SIDE = 1400     # 投影工作分辨率上限（长边），够判缝且免整幅 4000px 逐元
    RASTER_VALLEY_REL = 0.22    # 缝深判据：缝内峰值 ≤ 块内 p90 墨量 × 0.22
    RASTER_GUTTER_MIN = 0.008   # 缝宽 ≥ 该轴长度 0.8%
    RASTER_SIDE_MIN = 0.12      # 切出的两侧各承载 ≥12% 墨量（防削色标/图例当面板）
    RASTER_LEAF_MIN = 0.08      # 终叶墨量 ≥ 全图 8%

    def _raster_ink(self, im):
        """RGB → 墨迹布尔阵：暗或饱和即墨（白底与米白底都算空）。"""
        a = np.asarray(im.convert("RGB"), dtype=np.int16)
        return (a.max(axis=2) - a.min(axis=2) > 25) | (a.mean(axis=2) < 210)

    def _best_cut(self, ink, box):
        """框内找最强相对极小值缝。返回 (score, axis, mid, depth_ratio, frac) 或 None。"""
        x0, y0, x1, y1 = box
        sub = ink[y0:y1, x0:x1]
        h, w = sub.shape
        total = int(sub.sum())
        if total <= 0 or h < 40 or w < 40:
            return None
        profs = ((0, sub.mean(axis=0), w), (1, sub.mean(axis=1), h))
        ref = max(1e-6, float(np.percentile(np.concatenate([p for _, p, _ in profs]), 90)))
        thr = self.RASTER_VALLEY_REL * ref
        best = None
        for axis, prof, n in profs:
            low = prof < thr
            i = 0
            while i < n:
                if not low[i]:
                    i += 1
                    continue
                j = i
                while j < n and low[j]:
                    j += 1
                mid = int((i + j) / 2)
                if (j - i) >= max(2, int(self.RASTER_GUTTER_MIN * n)) and 0 < mid < n - 1:
                    if axis == 0:
                        lm, rm = int(sub[:, :mid].sum()), int(sub[:, mid:].sum())
                    else:
                        lm, rm = int(sub[:mid].sum()), int(sub[mid:].sum())
                    frac = min(lm, rm) / total
                    if frac >= self.RASTER_SIDE_MIN:
                        depth_ratio = float(prof[i:j].max()) / ref
                        strength = frac * (1.0 - depth_ratio)
                        score = strength + (j - i) / n
                        if best is None or score > best[0]:
                            best = (score, axis, (x0 if axis == 0 else y0) + mid, depth_ratio, frac, strength)
                i = j
        if best is None:
            return None
        return (best[0], best[1], best[2], best[3], best[4], best[5])

    def _cut_tree(self, ink, box, depth=0):
        """递归二分建树。节点 {box, axis, mid, strength, kids}。"""
        node = {"box": box, "axis": None, "mid": None, "strength": None, "kids": []}
        if depth >= 3:
            return node
        best = self._best_cut(ink, box)
        if best is None:
            return node
        _score, axis, mid = best[0], best[1], best[2]
        node["axis"], node["mid"], node["strength"] = axis, mid, best[5]
        x0, y0, x1, y1 = box
        if axis == 0:
            left, right = (x0, y0, mid, y1), (mid, y0, x1, y1)
        else:
            left, right = (x0, y0, x1, mid), (x0, mid, x1, y1)
        if left[2] - left[0] < 40 or right[2] - right[0] < 40 or left[3] - left[1] < 40 or right[3] - right[1] < 40:
            return node
        node["kids"] = [self._cut_tree(ink, left, depth + 1), self._cut_tree(ink, right, depth + 1)]
        return node

    @staticmethod
    def _tree_leaves(node):
        if not node["kids"]:
            return [node["box"]]
        return BaseAdapter._tree_leaves(node["kids"][0]) + BaseAdapter._tree_leaves(node["kids"][1])

    def _tree_collapse_to(self, node, n):
        """叶数多于目标时塌缩"最弱缝"（同缝两侧本就铺满父框 → 精确无重叠）。
        返回叶框列表；无法恰好收敛到 n 返回 None。"""
        leaves = self._tree_leaves(node)
        while len(leaves) > n:
            worst, wkey = None, None
            stack = [node]
            while stack:
                nd = stack.pop()
                if nd["kids"]:
                    if wkey is None or nd["strength"] < wkey:
                        wkey, worst = nd["strength"], nd
                    stack.extend(nd["kids"])
            if worst is None:
                return None
            worst["kids"], worst["axis"], worst["mid"], worst["strength"] = [], None, None, None
            leaves = self._tree_leaves(node)
        return leaves if len(leaves) == n else None

    @staticmethod
    def _tight(ink, box):
        """框内收边到墨迹包围盒。"""
        x0, y0, x1, y1 = box
        sub = ink[y0:y1, x0:x1]
        ys, xs = np.where(sub)
        if len(xs) == 0:
            return None
        return (x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1)

    def detect_panels_raster(self, raster, parent_caption):
        """复合位图 → 子面板（pt 坐标）。语义锚：题注必须声明 >=2 面板分句，否则不切。

        几何分块数与声明数不一致 → 按缝强度塌缩；仍不等或任一叶墨量 <8% → 拒切（不盲裁）。
        """
        if not self.panel_split or raster is None:
            return []
        segs, lead = self._caption_segments(parent_caption)
        n = len(segs)
        if n < 2:
            return []
        im, rr = raster["image"], raster["rect"]
        if im is None or rr is None or rr.width <= 0 or rr.height <= 0 or im.width < 120 or im.height < 120:
            return []
        k = min(1.0, self.RASTER_WORK_SIDE / float(max(im.size)))
        work = im if k == 1.0 else im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))))
        ink = self._raster_ink(work)
        total = float(ink.sum())
        if total <= 0:
            return []
        tree = self._cut_tree(ink, (0, 0, work.width, work.height))
        boxes = self._tree_collapse_to(tree, n)
        if not boxes or len(boxes) < 2:
            return []
        pad = 3.0
        out = []
        for b in boxes:
            t = self._tight(ink, b)
            if t is None:
                return []
            if float(ink[t[1]:t[3], t[0]:t[2]].sum()) / total < self.RASTER_LEAF_MIN:
                return []
            inv = 1.0 / k
            rect = fitz.Rect(rr.x0 + t[0] * inv / (im.width / rr.width) - pad,
                             rr.y0 + t[1] * inv / (im.height / rr.height) - pad,
                             rr.x0 + t[2] * inv / (im.width / rr.width) + pad,
                             rr.y0 + t[3] * inv / (im.height / rr.height) + pad) & rr
            if not rect.is_valid or rect.width < 40 or rect.height < 40:
                return []
            out.append({"rect": fitz.Rect(rect)})
        # 阅读序定字母（行聚簇后按 x）
        out.sort(key=lambda d: (d["rect"].y0, d["rect"].x0))
        rows, cur = [], []
        for d in out:
            r = d["rect"]
            if not cur:
                cur = [d]
                continue
            prev = cur[-1]["rect"]
            oy = min(prev.y1, r.y1) - max(prev.y0, r.y0)
            if oy > 0.5 * min(prev.height, r.height):
                cur.append(d)
            else:
                rows.append(cur)
                cur = [d]
        rows.append(cur)
        ordered = []
        for row in sorted(rows, key=lambda rr_: min(d["rect"].y0 for d in rr_)):
            ordered.extend(sorted(row, key=lambda d: d["rect"].x0))
        letters = sorted(segs)
        if len(ordered) != n:
            return []
        prefix = self._panel_fig_no_prefix(parent_caption)
        res = []
        for i, d in enumerate(ordered):
            l = letters[i]
            d["letter"] = l
            d["caption"] = f"{prefix}{l}. {lead} {segs[l]}".strip()
            d["row"], d["col"], d["source"] = 0, i, "raster"
            res.append(d)
        return res


    # ---------------- 面板级切分（v2.1，WORKORDER_panel_split_2026-10-18） ----------------

    def _panel_labels(self, page, fig_rect):
        """图形区域内找单字母面板标签：独立短 span、字号 ≤13、严格在题注上界之内。
        题注正文里的行内 (a) 位于 fig_rect.y1 之下 → 天然排除，不会把题注当标签。"""
        out = []
        probe = fitz.Rect(fig_rect.x0, max(40.0, fig_rect.y0 - 4), fig_rect.x1, fig_rect.y1 - 2)
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            return out
        for blk in blocks:
            if blk.get("type", 0) != 0:
                continue
            for line in blk.get("lines", []):
                for s in line.get("spans", []):
                    t = (s.get("text") or "").strip()
                    if not t or len(t) > 4:
                        continue
                    m = self.PANEL_LABEL_RE.match(t)
                    if not m:
                        continue
                    if (s.get("size") or 0) > 13:
                        continue
                    r = fitz.Rect(s["bbox"])
                    if r.y1 > probe.y1 or r.y0 < probe.y0 - 2 or not r.intersects(probe):
                        continue
                    out.append((m.group(1), r))
        return out

    @staticmethod
    def _cluster_anchors(vals, gap):
        """把标签坐标聚成网格行/列锚点（簇内最小值定标）。"""
        vs = sorted(vals)
        clusters = [[vs[0]]]
        for v in vs[1:]:
            if v - clusters[-1][-1] <= gap:
                clusters[-1].append(v)
            else:
                clusters.append([v])
        return [c[0] for c in clusters]

    @staticmethod
    def _band_index(anchors, mid, v):
        for i in range(len(anchors) - 1):
            if v < mid[i + 1] - 1e-6:
                return i
        return len(anchors) - 1

    def detect_panels(self, page, fig_rect, valid_images, page_drawings, parent_caption="", raster=None):
        """子面板切分。返回 [{'letter','rect','caption','source'}]；不过门禁返回 []（不切）。

        路线 A（标签网格）→ 失败时路线 B（复合位图内缝 + 题注声明数锚）。

        门禁（不变量 1：宁宽勿裁，绝不盲裁）：
        1. 标签集 = 从 'a' 起连续字母、≥2 个、无重复（重复 = 图内散点/图例误捕）；
        2. 严格网格：行簇 × 列簇 == 标签数，且一格一标签；
        3. 分带取相邻锚点中点（top-left 与 bottom-left 两种标签习惯都不偏切）；
        4. 每格必须有图形证据（位图覆盖格面积 ≥35% 或中心在格内的矢量路径），
           任一格无证据 → 整组拒切（绝不盲裁）；
        5. 裁后单面板 <60pt 或 <1200pt² → 整组拒切；有效面板 <2 → 不切。
        """
        if not self.panel_split or fig_rect is None:
            return []
        labels = self._panel_labels(page, fig_rect)
        out = self._panels_from_labels(labels, fig_rect, valid_images, page_drawings, parent_caption, page)
        if out:
            return out
        return self.detect_panels_raster(raster, parent_caption)

    def _panels_from_labels(self, labels, fig_rect, valid_images, page_drawings, parent_caption, page):
        """路线 A：文本层单字母标签的严格网格切分。"""
        if len(labels) < 2:
            return []
        letters = sorted({l for l, _ in labels})
        if len(letters) != len(labels):
            return []  # 同字母多次出现：散点标注/图例，非面板网格
        if letters != [chr(97 + i) for i in range(len(letters))]:
            return []  # 必须 a 起头连续
        rects = {l: r for l, r in labels}

        row_anchors = self._cluster_anchors([r.y0 for r in rects.values()], 20.0)
        col_anchors = self._cluster_anchors([r.x0 for r in rects.values()], 20.0)
        if len(row_anchors) * len(col_anchors) != len(rects):
            return []  # 非规整网格 → 不切
        row_mid = [fig_rect.y0] + [(row_anchors[i] + row_anchors[i + 1]) / 2
                                   for i in range(len(row_anchors) - 1)] + [fig_rect.y1]
        col_mid = [fig_rect.x0] + [(col_anchors[i] + col_anchors[i + 1]) / 2
                                   for i in range(len(col_anchors) - 1)] + [fig_rect.x1]

        cells = {}
        for l, r in rects.items():
            ri = self._band_index(row_anchors, row_mid, r.y0)
            ci = self._band_index(col_anchors, col_mid, r.x0)
            if (ri, ci) in cells:
                return []  # 同格双标签 → 网格判定失败
            cells[(ri, ci)] = (l, fitz.Rect(col_mid[ci], row_mid[ri], col_mid[ci + 1], row_mid[ri + 1]))

        segs, lead = self._caption_segments(parent_caption)
        fig_prefix = self._panel_fig_no_prefix(parent_caption)
        out = []
        for (ri, ci), (l, cell) in sorted(cells.items()):
            ink = self._panel_ink(page, cell, valid_images, page_drawings)
            if ink is None:
                return []  # 任一格无图形证据 → 整组拒切
            if ink.width < 60 or ink.height < 60 or ink.get_area() < 1200:
                return []
            seg = segs.get(l, "")
            cap = f"{fig_prefix}{l}. {lead} {seg}".strip() if seg else f"（面板 {l}）{parent_caption}"
            out.append({"letter": l, "rect": ink, "caption": cap, "row": ri, "col": ci,
                        "source": "label"})
        if len(out) < 2:
            return []
        return out

    def _panel_ink(self, page, cell, valid_images, page_drawings):
        """格内图形证据并集：位图（按覆盖格面积比 ≥0.35 供证，复合大图可同时为多格供证）
        ∪ 中心落在格内的矢量路径 ∪ 格内刻度/单位文字，最后 ∩cell 收边。
        无图形证据返回 None（刻度文字不算独立证据）。"""
        parts = []
        cell_area = max(1.0, cell.get_area())
        for vi in valid_images:
            r = vi["rect"]
            if not r:
                continue
            inter = r & cell
            if not inter.is_valid or inter.get_area() / cell_area < 0.35:
                continue
            parts.append(fitz.Rect(inter))
        for d in page_drawings:
            r = d["rect"]
            if r.y1 <= 64:
                continue
            cx, cy = (r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0
            if cell.contains(fitz.Point(cx, cy)):
                parts.append(fitz.Rect(r))
        if not parts:
            return None
        u = parts[0]
        for r in parts[1:]:
            u = u | r
        if u.get_area() < 1200:
            return None
        # 刻度数字/轴单位/色标文字并入（否则面板裁掉轴刻度），再 ∩cell 防吃到邻栏
        u = self._merge_spans(page, u, None, max(40.0, cell.y0 - 10), cell.y1 + 10, 10.0, 10.0)
        u = u & cell
        return u if u.is_valid and u.get_area() >= 1200 else None

    _CAP_SEG_SPLIT = re.compile(r"[\[\(\{]\s*([a-z])\s*[\]\)\}][\.\:\s]")

    @classmethod
    def _caption_segments(cls, caption):
        """父题注按 '(a) … (b) …' 分句 → ({letter: 分句}, 主句)。

        门禁：分句 <20 字符、成段字母 <2、或字母不从 'a' 连续 → 判"无可信面板题注"
        返回 ({}, 主句)。字母缺口（如 (a)(c) 跳 b）说明有面板没写成段，照用必错配，
        宁可整组继承父题注。主句 = 第一个标记之前的文字，供面板题注前置。"""
        if not caption:
            return {}, ""
        parts = cls._CAP_SEG_SPLIT.split(caption)
        # parts = [主句, l1, body1, l2, body2, ...]
        lead = re.sub(r"^\s*(?:(?:Supplementary|Supplemental|Appendix|Extended\s+Data)\s+)?"
                      r"(?:Fig(?:ure)?\.?|图|附图)\s*S?\d+[a-zA-Z]?[\.\:\s]*", "", parts[0],
                      flags=re.IGNORECASE).strip()
        found = {}
        for i in range(1, len(parts) - 1, 2):
            body = re.sub(r"\s+", " ", parts[i + 1]).strip()
            if len(body) >= 20:
                found[parts[i]] = body
        if len(found) < 2:
            return {}, lead
        letters = sorted(found)
        if letters != [chr(97 + i) for i in range(len(letters))]:
            return {}, lead
        return found, lead

    @staticmethod
    def _panel_fig_no_prefix(parent_caption):
        """面板题注编号前缀：取父题注开头的 'Fig. 4' / 'Figure S2' / '图 3'，拼字母用。"""
        m = re.match(
            r"^\s*((?:(?:Supplementary|Supplemental|Appendix|Extended\s+Data)\s+)?"
            r"(?:Fig(?:ure)?\.?|图|附图)\s*S?\d+[a-zA-Z]?)",
            parent_caption or "", re.IGNORECASE)
        return m.group(1).strip().rstrip(".") if m else "Fig."

    def _merge_spans(self, page, u, text_spans, y_top, y_bottom, pad_above, pad_below):
        """合并图形近旁的文本标注：刻度数字、轴单位、面板字母 (a)(b)、色标文字（懒计算）。"""
        spans = text_spans
        if spans is None:
            try:
                spans = [
                    fitz.Rect(s["bbox"])
                    for blk in page.get_text("dict")["blocks"]
                    for line in blk.get("lines", [])
                    for s in line.get("spans", [])
                ]
            except Exception:
                spans = []
        elif callable(spans):
            spans = spans()
        if spans:
            exp = fitz.Rect(u.x0 - 20, u.y0 - pad_above, u.x1 + 20, u.y1 + pad_below)
            u_start_y = u.y0
            for sr in spans:
                if sr.y0 >= y_top and sr.y1 <= y_bottom and sr.intersects(exp):
                    # header_guard: 图簇未触及页眉区(u.y0>64)时，页眉文本行(y1≤64)不得并入
                    if sr.y1 <= 64 and u_start_y > 64:
                        continue
                    u = u | sr
        return u

    def _figure_below_caption(self, page, cap_rect, valid_images, page_drawings, text_spans, cx0, cx1):
        """题注下方的紧邻图形：位图起点距题注底 ≤60pt 直抽；矢量簇向下生长收全竖排面板。"""
        page_rect = page.rect
        bottom_lim = min(page_rect.height - 35.0, cap_rect.y1 + 460.0)
        band = fitz.Rect(cx0, max(40.0, cap_rect.y1 - 8.0), cx1, bottom_lim)
        if band.height < 60:
            return None, None

        cands = [vi for vi in valid_images
                 if vi["rect"] and vi["rect"].intersects(band)
                 and cap_rect.y1 - 12 <= vi["rect"].y0 <= cap_rect.y1 + 60
                 and vi["rect"].height <= 520]
        if cands:
            cands.sort(key=lambda vi: vi["rect"].y0 - cap_rect.y1)
            return None, cands[0]

        drs = [d["rect"] for d in page_drawings
               if d["rect"].intersects(band) and cap_rect.y1 - 12 <= d["rect"].y0 <= cap_rect.y1 + 60]
        if not drs:
            return None, None
        u = drs[0]
        for r in drs[1:]:
            u = u | r
        grew, guard = True, 0
        while grew and guard < 12:
            grew, guard = False, guard + 1
            for d in page_drawings:
                r = d["rect"]
                if r.intersects(band) and u.y0 - 10 <= r.y0 <= u.y1 + 14 and r.y1 > u.y1:
                    u = u | r
                    grew = True
        u = self._merge_spans(page, u, text_spans, max(40.0, cap_rect.y1 - 2), bottom_lim, 14.0, 16.0)
        clip = fitz.Rect(max(25, u.x0 - 6), max(cap_rect.y1 - 2, u.y0 - 6),
                         min(page_rect.width - 25, u.x1 + 6), min(bottom_lim + 8, u.y1 + 6))
        return clip, None

    def _figure_beside_caption(self, page, cap_rect, valid_images, page_drawings, text_spans):
        """题注与图左右并排（老刊侧置图注/双联版式）。
        守卫：仅窄题注块（调用方限制）、位图与题注纵向重叠 >=35%、距题注边 <=320pt、
        排除整页扫描与超大 union，防误捕相邻联内容。"""
        page_rect = page.rect
        for side in ("right", "left"):
            if side == "right":
                win = fitz.Rect(cap_rect.x1 + 2, max(40.0, cap_rect.y0 - 25),
                                min(page_rect.width - 25, cap_rect.x1 + 320.0),
                                cap_rect.y1 + 25)
                near = lambda r: r.x0 >= cap_rect.x1 - 12
            else:
                win = fitz.Rect(max(25.0, cap_rect.x0 - 320.0), max(40.0, cap_rect.y0 - 25),
                                cap_rect.x0 - 2, cap_rect.y1 + 25)
                near = lambda r: r.x1 <= cap_rect.x0 + 12
            if win.x1 - win.x0 < 80 or win.y1 - win.y0 < 60:
                continue
            side_imgs = []
            for vi in valid_images:
                r = vi["rect"]
                if not r or not near(r) or r.height > 540:
                    continue
                if not r.intersects(win):
                    continue
                ov = min(r.y1, win.y1) - max(r.y0, win.y0)
                if ov > 0 and ov / max(1.0, r.height) >= 0.35:
                    side_imgs.append(vi)
            side_dr = [d["rect"] for d in page_drawings
                       if near(d["rect"]) and d["rect"].intersects(win) and d["rect"].y0 >= 40]
            if len(side_imgs) == 1 and not side_dr:
                return None, side_imgs[0]
            parts = [vi["rect"] for vi in side_imgs] + side_dr
            if not parts:
                continue
            u = parts[0]
            for r in parts[1:]:
                u = u | r
            if (u.y1 - u.y0) > 560:
                continue
            u = self._merge_spans(page, u, text_spans, 40.0, page_rect.height - 40.0, 12.0, 12.0)
            clip = fitz.Rect(max(25, u.x0 - 6), max(40, u.y0 - 6),
                             min(page_rect.width - 25, u.x1 + 6),
                             min(page_rect.height - 40, u.y1 + 6))
            if clip.height >= 60 and clip.width >= 80:
                return clip, None
        return None, None