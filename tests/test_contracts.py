"""契约测试：锁住历史上反复翻车的四条不变式。

不是全量测试，只覆盖注释里写满"实测教训"的那几条——把教训从注释变成可执行断言。
运行：python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

import ratings
from adapters import get_adapter
import engine
from engine import parse_author_terms, parse_item_keys
from family_rules import journal_family


class JournalFamilyContract(unittest.TestCase):
    """family_rules 是路由与批调共用的单一事实源，改动会静默改变抽图行为。"""

    def test_known_families(self):
        cases = {
            "Geophysical Research Letters": "agu",
            "Journal of Geophysical Research: Atmospheres": "agu",
            "Nature Communications": "nature",
            "Quaternary Science Reviews": "elsevier",
            "Climate of the Past": "copernicus",
            "Global Change Biology": "wiley",
        }
        for journal, expected in cases.items():
            with self.subTest(journal=journal):
                self.assertEqual(journal_family(journal), expected)

    def test_jgr_atmospheres_not_stolen_by_mdpi(self):
        # §八② 2026-10-19：mdpi 的关键词表里有裸 "atmosphere"，AGU 规则必须排在前面
        self.assertEqual(journal_family("JGR Atmospheres"), "agu")
        self.assertEqual(journal_family("Journal of Geophysical Research: Atmospheres"), "agu")

    def test_rule_priority_elsevier_beats_mdpi(self):
        # 两个家族的关键词都命中时，靠 JOURNAL_RULES 顺序决出（elsevier 在前）
        self.assertEqual(journal_family("Remote Sensing of Environment"), "elsevier")
        self.assertEqual(journal_family("Remote Sensing"), "mdpi")
        self.assertEqual(journal_family("Quaternary Geochronology"), "elsevier")

    def test_exact_family_overrides_keywords(self):
        self.assertEqual(journal_family("Science"), "aaas")
        self.assertEqual(journal_family("Catena"), "elsevier")
        self.assertEqual(journal_family("Geology"), "gsw")

    def test_holocene_is_generic_on_purpose(self):
        # The Holocene 是 SAGE 刊，误记 Wiley 的映射已被显式删除，必须落 generic
        self.assertIsNone(journal_family("The Holocene"))

    def test_unknown_and_empty(self):
        self.assertIsNone(journal_family("Journal of Nothing"))
        self.assertIsNone(journal_family(""))
        self.assertIsNone(journal_family(None))


class AdapterRoutingContract(unittest.TestCase):
    """路由只认刊名；doc=None 时刊名分支必须先生效（publisher 字段 83% 为空）。"""

    def test_routing_by_journal_name(self):
        cases = {
            "Geophysical Research Letters": "agu_wiley",
            "Journal of Geophysical Research: Atmospheres": "agu_wiley",
            "Nature Geoscience": "nature_portfolio",
            "Quaternary Science Reviews": "elsevier",
            "Progress in Physical Geography": "generic",
            "Journal of Nothing": "generic",
        }
        for journal, expected in cases.items():
            with self.subTest(journal=journal):
                self.assertEqual(get_adapter(journal, None).name, expected)

    def test_panel_split_follows_family(self):
        # elsevier/agu/nature 开面板切分；generic 不开（v2.1 契约）
        self.assertTrue(get_adapter("Quaternary Science Reviews", None).panel_split)
        self.assertTrue(get_adapter("Geophysical Research Letters", None).panel_split)
        self.assertTrue(get_adapter("Nature Communications", None).panel_split)
        self.assertFalse(get_adapter("Journal of Nothing", None).panel_split)


class FigureNoNormalisationContract(unittest.TestCase):
    """fig_no 有 1024 种原始拼写；评分键必须归一，否则重抽后评分对不上。"""

    def test_spellings_collapse_to_one_key(self):
        # 只抹空白（含换行与 nbsp）与点号 + 转小写；同前缀的不同写法必须归一
        same_key = ["Fig.1", "Fig. 1", "Fig.\n 1", "FIG. 1", "Fig.\xa0 1", " Fig.1 ", "Fig .1"]
        self.assertEqual({ratings.norm_fig(text) for text in same_key}, {"fig1"})

    def test_prefix_variance_is_not_normalised(self):
        # 已知缺口（2026-11-15 实测记录）：norm_fig 不把 "Figure" 收敛成 "Fig"，故重抽若把
        # "Fig. 1" 写成 "Figure 1"，评分键会换、旧评分静默失联。修它要迁移 ratings.json
        # （docstring 记录受影响键 102 个），属数据迁移决策，未擅自改。
        self.assertNotEqual(ratings.norm_fig("Figure 1"), ratings.norm_fig("Fig. 1"))

    def test_key_shape(self):
        self.assertEqual(ratings.make_key(" abc123 ", "Fig. 5"), "ABC123|fig5")
        self.assertEqual(ratings.make_key("ABC123", "Figure 5"), "ABC123|figure5")

    def test_empty_is_falsy(self):
        self.assertEqual(ratings.norm_fig(None), "")
        self.assertEqual(ratings.norm_fig(""), "")


class RatingsSidecarContract(unittest.TestCase):
    """评分是人工标注，必须与可重抽的 figures 表物理隔离，且原子写。"""

    def setUp(self):
        self._original_path = ratings.RATINGS_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        ratings.RATINGS_PATH = os.path.join(self._tmpdir.name, "ratings.json")
        ratings._state["mtime"] = None
        ratings._state["data"] = {}
        ratings._state["lookup"] = None

    def tearDown(self):
        ratings.RATINGS_PATH = self._original_path
        ratings._state["mtime"] = None
        ratings._state["data"] = {}
        ratings._state["lookup"] = None
        self._tmpdir.cleanup()

    def test_round_trip_and_clear(self):
        self.assertEqual(ratings.set_rating("KEY1", "Fig. 3", 5), 5)
        self.assertIn(("KEY1", "fig3"), ratings.as_lookup())
        self.assertEqual(ratings.set_rating("key1", "Figure 3", 4), 4)  # 键归一后是同一行
        self.assertEqual(ratings.set_rating("KEY1", "Fig.3", 0), 0)     # 0 = 清除
        self.assertNotIn(("KEY1", "fig3"), ratings.as_lookup())

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            ratings.set_rating("", "Fig.1", 3)
        with self.assertRaises(ValueError):
            ratings.set_rating("KEY1", "", 3)
        with self.assertRaises(ValueError):
            ratings.set_rating("KEY1", "Fig.1", "not-a-number")

    def test_missing_file_yields_empty(self):
        self.assertEqual(ratings.load(), {})


class _StubEncoder:
    def encode_query(self, text):
        return np.zeros(384, dtype=np.float32)


def _meta(row_id, item_key, fig_no, origin="whole", journal="Journal A", caption=None, title=None, year=2020):
    title = title or f"Title {row_id}"
    caption = caption or f"Figure {fig_no}. caption {row_id}"
    return {
        "id": row_id, "item_key": item_key, "att_key": "", "title": title, "year": year,
        "journal": journal, "journal_abbr": "J. A.", "authors": "A. Author",
        "fig_no": fig_no, "caption": caption, "context_text": "", "image_path": "",
        "thumb_name": "", "page_no": 1, "origin": origin, "panels_json": "",
        "authors_norm": "", "_cap_l": caption.lower(), "_title_l": title.lower(),
        "_fig_l": fig_no.lower(), "_dedup": (title.lower(), fig_no.lower()),
    }


def _make_searcher(metas):
    from engine import FigureSearcher

    searcher = object.__new__(FigureSearcher)
    searcher.db = None                      # _fts_candidates 内部捕获异常后返回 []
    searcher.encoder = _StubEncoder()
    searcher._metas = metas
    searcher._M = np.zeros((len(metas), 384), dtype=np.float32)
    searcher._id2idx = {meta["id"]: i for i, meta in enumerate(metas)}
    searcher._sig = None
    searcher._ensure_cache = lambda: None    # 绕开 sqlite/模型，只测打分与切片契约
    return searcher


class SearchSlicingContract(unittest.TestCase):
    """offset 是远程 API 的分页基础；origin 决定画廊默认视图不出面板行。"""

    def setUp(self):
        self.metas = [
            _meta(1, "KEYA", "Figure 1", caption="Holocene moisture record from lake X"),
            _meta(2, "KEYA", "Figure 2", caption="Temperature reconstruction"),
            _meta(3, "KEYB", "Figure 3", caption="Vegetation dynamics"),
            _meta(4, "KEYB", "Figure 4", origin="panel", caption="Panel a of figure 4"),
            _meta(5, "KEYC", "Figure 5", caption="Holocene carbon burial"),
        ]
        self.searcher = _make_searcher(self.metas)

    def test_offset_slices_the_same_ranking(self):
        base = self.searcher.search("Holocene", top_k=10)
        self.assertEqual(len(base), 5)
        window = self.searcher.search("Holocene", top_k=2, offset=1)
        self.assertEqual([item["id"] for item in window], [item["id"] for item in base[1:3]])

    def test_keyword_bonus_ranks_exact_phrase_first(self):
        top = self.searcher.search("Holocene", top_k=1)
        self.assertIn("Holocene", top[0]["caption"])

    def test_origin_whole_excludes_panels(self):
        whole = self.searcher.search("", journal_filter="Journal A", origin="whole")
        self.assertEqual({item["origin"] for item in whole}, {"whole"})
        self.assertEqual(len(whole), 4)
        every = self.searcher.search("", journal_filter="Journal A")
        self.assertEqual(len(every), 5)

    def test_item_key_filter_returns_whole_paper(self):
        hits = self.searcher.search("", item_key="KEYB")
        self.assertEqual({item["item_key"] for item in hits}, {"KEYB"})
        self.assertEqual(len(hits), 2)

    def test_rating_min_filters_by_sidecar_key(self):
        lookup = {("KEYA", "figure1"): 5, ("KEYC", "figure5"): 2}
        hits = self.searcher.search("Holocene", top_k=10, rating_min=4, rating_map=lookup)
        self.assertEqual([item["item_key"] for item in hits], ["KEYA"])
        self.assertEqual(hits[0]["rating"], 5)

    def test_dedup_on_title_and_fig_no(self):
        metas = [
            _meta(10, "PREPRINT", "Figure 1", title="Same Title"),
            _meta(11, "PUBLISHED", "Figure 1", title="Same Title"),
        ]
        searcher = _make_searcher(metas)
        hits = searcher.search("Figure", top_k=10)
        self.assertEqual(len(hits), 1)

    def test_empty_query_without_filters_returns_nothing(self):
        # 防全库 dump：无词且无过滤 = 空操作
        self.assertEqual(self.searcher.search(""), [])


class ItemKeyParsingTest(unittest.TestCase):
    """按 Item Key 查图：入口解析必须容错（分号/逗号/空白、KEY- 前缀、大小写）。"""

    def test_single_key(self):
        self.assertEqual(parse_item_keys("8btqjnke"), {"8BTQJNKE"})

    def test_multi_separators(self):
        self.assertEqual(parse_item_keys("A1B2C3D4;E5F6G7H8,I9J0K1L2，M3N4O5P6 Q7R8S9T0"),
                         {"A1B2C3D4", "E5F6G7H8", "I9J0K1L2", "M3N4O5P6", "Q7R8S9T0"})

    def test_prefix_and_blank(self):
        self.assertEqual(parse_item_keys(" KEY-abcd1234 ; "), {"ABCD1234"})
        self.assertEqual(parse_item_keys(""), set())
        self.assertEqual(parse_item_keys(None), set())


class AuthorTermsTest(unittest.TestCase):
    """作者多值解析：只按分号/逗号切，作者名里的空格必须保留。"""

    def test_single(self):
        self.assertEqual(parse_author_terms("唐丽雅"), ["唐丽雅"])

    def test_multi_and_space_preserved(self):
        self.assertEqual(parse_author_terms("唐丽雅;Zhang San，Huang"), ["唐丽雅", "zhang san", "huang"])

    def test_dedupe_and_blank(self):
        self.assertEqual(parse_author_terms("Tang;tang;; "), ["tang"])
        self.assertEqual(parse_author_terms(""), [])
        self.assertEqual(parse_author_terms(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
