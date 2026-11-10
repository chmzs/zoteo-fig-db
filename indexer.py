"""
Zotero GeoFigure Indexer (fig_db)
Scans Zotero PDF attachments, extracts figures, encodes with multilingual-e5-small, saves to SQLite.

条目附件选择规则:
- 只处理 contentType='application/pdf'（EPUB/HTML 快照暂跳过：无图注结构，收益低，长期任务）
- 排除"沉浸式翻译/双语"对照版 PDF 与明显补充材料（supplement/SI/附件）
- 一个条目挂多个 PDF 时，优先符合 "作者 X.-YYYY-标题" 主文命名惯例的 PDF
"""

import os
import tempfile
import re
import shutil
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from author_norm import build_authors_norm
from engine import (
    Encoder,
    FigureDB,
    FigureExtractor,
    _display_authors,
    resolve_abbr,
    zot_abbr_plausible,
)

ZOTERO_DIR = r"D:\Zotero"
STORAGE_DIR = os.path.join(ZOTERO_DIR, "storage")
TEMP_DB = os.path.join(tempfile.gettempdir(), f"zotero_fig_index_{os.getpid()}.sqlite")

# 排除的 PDF（双语对照版 / 明显补充材料）
EXCLUDE_RE = re.compile(
    r"沉浸式翻译|双语|translation|supplement|supporting[- _]?info|_SI[-_.]|(?<![a-z])SI[-_.]|附件",
    re.IGNORECASE,
)
# 主文命名惯例: "Cooper D.-2021-A kingdom..." / "Zhou S.-2025-Temperature..."
MAIN_PDF_RE = re.compile(r"[A-Za-z\u4e00-\u9fff]+(?:\s+[A-Z]\.)+.*\d{4}", re.IGNORECASE)


def _resolve_pdf(att_key, att_path):
    if att_path and att_path.startswith("storage:"):
        fname = att_path[len("storage:"):]
        p = os.path.join(STORAGE_DIR, att_key, fname)
        if os.path.exists(p):
            return p
    att_folder = os.path.join(STORAGE_DIR, att_key)
    if os.path.exists(att_folder):
        for f in sorted(os.listdir(att_folder)):
            if f.lower().endswith(".pdf"):
                return os.path.join(att_folder, f)
    return None


_META_SQL = """
    SELECT
        i.key as item_key,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'title') as title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'date') as date_val,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'publicationTitle') as publication_title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'journalAbbreviation') as journal_abbr,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'publisher') as publisher,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'bookTitle') as book_title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'proceedingsTitle') as proceedings_title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'university') as university,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'abstractNote') as abstract
    FROM items i
"""


def _resolve_venue(publication_title, journal_abbr, proceedings_title,
                   book_title, university, publisher):
    """刊名回退链（indexer 与 backfill_meta 共用，防两处逻辑漂移）。

    期刊论文取 publicationTitle；书籍 / 学位论文 / 会议论文的"刊名"实际存在
    publisher / university / bookTitle / proceedingsTitle。只查 publicationTitle
    会让这些条目必然为空（2026-11-10 实测 136 篇）。

    只有真期刊名才采用 Zotero 的 journalAbbreviation；回退来源直接存全称，
    免得 journal_abbr_str 把 "Science Press" 切成 "S. P." 这类无意义缩写。
    """
    primary = (publication_title or "").strip()
    venue = (primary
             or (proceedings_title or "").strip()
             or (book_title or "").strip()
             or (university or "").strip()
             or (publisher or "").strip())
    venue_abbr = (journal_abbr or "").strip() if primary else venue
    return venue, venue_abbr


def _parse_year(date_val):
    if not date_val:
        return 0
    match = re.search(r"\b(19\d\d|20\d\d)\b", str(date_val))
    return int(match.group(1)) if match else 0


def _read_creators(cursor):
    """作者回退链：书籍/编著取 editor、软件取 programmer。

    只查 'author' 会让这类条目的作者列恒空（2026-11-10 实测 15 篇，其中
    author 类型的为 0 篇）。按 author > editor > programmer 优先取一组。
    """
    cursor.execute("""
        SELECT i.key, c.firstName, c.lastName, ic.orderIndex, ct.creatorType
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
        JOIN items i ON ic.itemID = i.itemID
        WHERE ct.creatorType IN ('author', 'editor', 'programmer')
        ORDER BY i.key, ic.orderIndex
    """)
    by_role = {}
    for key, first_name, last_name, _oi, role in cursor.fetchall():
        f = (first_name or "").strip()
        l = (last_name or "").strip()
        full = f"{f} {l}".strip() if f else l
        if full:
            by_role.setdefault(key, {}).setdefault(role, []).append(full)
    authors_map = {}
    for key, roles in by_role.items():
        authors_map[key] = (roles.get("author") or roles.get("editor")
                            or roles.get("programmer") or [])
    return authors_map


def get_zotero_meta_map(keys=None):
    """读 Zotero 条目元数据（不要求有 PDF 附件），供全量回填使用。

    keys 给定时只返回这些 item_key（大写比对）。返回值：
      {item_key: {title, year, journal, journal_abbr, authors, authors_norm}}

    与扫描模式相反，这里**优先读主库** zotero.sqlite：.bak 是 Zotero 关闭时的
    快照，用户在应用内补录的年份/作者只存在于主库（2026-11-10 实测 .bak 落后
    一天，5 篇补录全丢失）。复制失败才退 .bak。
    """
    src_db = os.path.join(ZOTERO_DIR, "zotero.sqlite")
    backup_db = os.path.join(ZOTERO_DIR, "zotero.sqlite.bak")
    try:
        shutil.copy2(src_db, TEMP_DB)
    except OSError:
        shutil.copy2(backup_db, TEMP_DB)
    conn = sqlite3.connect(TEMP_DB)
    cursor = conn.cursor()
    cursor.execute(_META_SQL)
    rows = cursor.fetchall()
    authors_map = _read_creators(cursor)
    conn.close()
    try:
        os.remove(TEMP_DB)
    except Exception:
        pass

    wanted = {k.upper() for k in keys} if keys else None
    meta_map = {}
    for (item_key, title, date_val, publication_title, journal_abbr,
         publisher, book_title, proceedings_title, university, _abstract) in rows:
        if wanted is not None and item_key.upper() not in wanted:
            continue
        primary = (publication_title or "").strip()
        venue, _unused = _resolve_venue(
            publication_title, journal_abbr, proceedings_title,
            book_title, university, publisher)
        creators = authors_map.get(item_key, [])
        meta_map[item_key] = {
            "title": title or "",
            "year": _parse_year(date_val),
            "journal": venue,
            "journal_abbr_raw": (journal_abbr or "").strip() if primary else "",
            "from_primary_venue": bool(primary),
            "authors": _display_authors(creators[0] if creators else ""),
            "authors_norm": build_authors_norm(creators),
        }

    # 缩写美化必须与 indexer 同一条路径：按刊名分组挑一个通过合理性校验的
    # Zotero 缩写，再 resolve_abbr 统一格式化。直接写 Zotero 原始值会把
    # "Ecol. Monogr." 退化回 "ECOL MONOGR"（2026-11-10 dry-run 实测 5322 行）。
    groups = {}
    for meta in meta_map.values():
        norm_key = re.sub(r"[^a-z0-9&]", "", (meta["journal"] or "").lower())
        groups.setdefault(norm_key, []).append(meta)
    for group in groups.values():
        consensus = ""
        for meta in group:
            raw = meta["journal_abbr_raw"]
            if raw and zot_abbr_plausible(meta["journal"], raw):
                consensus = raw
                break
        for meta in group:
            # 回退来源（出版社/授予单位/书名）直接存全称，避免被切成 "S. P."
            meta["journal_abbr"] = (resolve_abbr(meta["journal"], consensus)
                                    if meta["from_primary_venue"] else meta["journal"])
    for meta in meta_map.values():
        meta.pop("journal_abbr_raw", None)
        meta.pop("from_primary_venue", None)
    return meta_map


def get_zotero_items_with_pdfs(limit=50, filter_journal=None):
    src_db = os.path.join(ZOTERO_DIR, "zotero.sqlite.bak")
    if not os.path.exists(src_db):
        src_db = os.path.join(ZOTERO_DIR, "zotero.sqlite")
    shutil.copy2(src_db, TEMP_DB)

    conn = sqlite3.connect(TEMP_DB)
    cursor = conn.cursor()

    query = """
    SELECT
        i.key as item_key,
        att_i.key as att_key,
        ia.path as att_path,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'title') as title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'date') as date_val,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'publicationTitle') as journal,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'journalAbbreviation') as journal_abbr,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'publisher') as publisher,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'bookTitle') as book_title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'proceedingsTitle') as proceedings_title,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'university') as university,
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'abstractNote') as abstract
    FROM itemAttachments ia
    JOIN items att_i ON ia.itemID = att_i.itemID
    JOIN items i ON ia.parentItemID = i.itemID
    WHERE ia.contentType = 'application/pdf'
    """
    if filter_journal:
        query += f" AND journal LIKE '%{filter_journal}%'"
    query += " ORDER BY i.dateModified DESC, ia.itemID"

    cursor.execute(query)
    rows = cursor.fetchall()

    authors_map = _read_creators(cursor)
    conn.close()
    try:
        os.remove(TEMP_DB)
    except Exception:
        pass

    # 按父条目聚合全部 PDF 附件
    by_item = {}
    order = []
    for r in rows:
        (item_key, att_key, att_path, title, date_val, publication_title, journal_abbr,
         publisher, book_title, proceedings_title, university, abstract) = r
        if item_key not in by_item:
            venue, venue_abbr = _resolve_venue(
                publication_title, journal_abbr, proceedings_title,
                book_title, university, publisher)
            by_item[item_key] = {
                "item_key": item_key,
                "title": title or "",
                "date_val": date_val,
                "journal": venue,
                "journal_abbr": venue_abbr,
                "publisher": (publisher or "").strip(),
                "abstract": (abstract or "").strip(),
                "attachments": [],
            }
            order.append(item_key)
        by_item[item_key]["attachments"].append((att_key, att_path))

    results = []
    for item_key in order:
        info = by_item[item_key]
        year = 0
        if info["date_val"]:
            m = re.search(r"\b(19\d\d|20\d\d)\b", str(info["date_val"]))
            if m:
                year = int(m.group(1))

        candidates = []
        for att_key, att_path in info["attachments"]:
            pdf_file = _resolve_pdf(att_key, att_path)
            if not pdf_file:
                continue
            base = os.path.basename(pdf_file)
            if EXCLUDE_RE.search(base):
                continue  # 双语对照版 / 补充材料
            candidates.append((att_key, pdf_file, base))

        if not candidates:
            continue

        # 主文命名惯例优先，否则取第一个合规 PDF
        main = None
        for c in candidates:
            if MAIN_PDF_RE.search(c[2]):
                main = c
                break
        if main is None:
            main = candidates[0]

        a = authors_map.get(item_key, [])
        results.append({
            "item_key": item_key,
            "att_key": main[0],
            "publisher": info.get("publisher", ""),
            "pdf_path": main[1],
            "title": info["title"],
            "year": year,
            "journal": info["journal"],
            "journal_abbr_raw": info.get("journal_abbr", ""),
            "authors": _display_authors(a[0] if a else ""),
            "authors_norm": build_authors_norm(a),  # 全部作者归一（中文↔拼音检索用）
            "abstract": info.get("abstract", ""),
            "n_pdfs": len(candidates),
        })
        if limit and len(results) >= limit:
            break

    _finalise_abbr(results)
    return results


def _finalise_abbr(results):
    """同一期刊多条条目取合法 journalAbbreviation 的共识值（修复个别条目字段错配导致的显示不一致）"""
    groups = {}
    for r in results:
        nk = re.sub(r"[^a-z0-9&]", "", (r.get("journal") or "").lower())
        groups.setdefault(nk, []).append(r)
    for rs in groups.values():
        cons = ""
        for r in rs:
            z = (r.get("journal_abbr_raw") or "").strip()
            if z and zot_abbr_plausible(r.get("journal", ""), z):
                cons = z
                break
        for r in rs:
            r["journal_abbr"] = resolve_abbr(r.get("journal", ""), cons)
        for r in rs:
            r.pop("journal_abbr_raw", None)


def index_papers(papers, force_reindex=False):
    extractor = FigureExtractor()
    encoder = Encoder()
    db = FigureDB()

    total_extracted = 0
    print(f"Starting indexing of {len(papers)} papers...")

    for idx, p in enumerate(papers):
        item_key = p["item_key"]
        att_key = p.get("att_key", "")
        if not force_reindex and db.exists_item(item_key):
            continue

        figs = extractor.extract_from_pdf(
            pdf_path=p["pdf_path"],
            item_key=item_key,
            att_key=att_key,
            title=p["title"],
            year=p["year"],
            journal=p["journal"],
        )

        for f in figs:
            emb = encoder.encode(f["caption"])
            f["embedding"] = emb
            f["journal_abbr"] = p.get("journal_abbr") or ""
            f["authors"] = p.get("authors") or ""
            f["context_text"] = p.get("abstract") or ""
            f["authors_norm"] = p.get("authors_norm") or ""
            db.insert_figure(f)
            total_extracted += 1

        print(f"[{idx+1}/{len(papers)}] {item_key} ({p['journal']}) -> {len(figs)} figs")

    stats = db.get_stats()
    print("\nIndexing complete!")
    print(f"Total papers in DB: {stats['total_papers']}, Total figures in DB: {stats['total_figures']}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Zotero GeoFigure Indexer")
    parser.add_argument("--limit", type=int, default=10, help="Number of papers to index")
    parser.add_argument("--journal", type=str, default=None, help="Filter journal name")
    parser.add_argument("--force", action="store_true", help="Force re-indexing existing items")
    args = parser.parse_args()

    papers = get_zotero_items_with_pdfs(limit=args.limit, filter_journal=args.journal)
    print(f"Found {len(papers)} candidate papers with valid main PDFs.")
    index_papers(papers, force_reindex=args.force)
