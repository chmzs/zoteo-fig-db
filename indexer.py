"""
Zotero GeoFigure Indexer (fig_db)
Scans Zotero PDF attachments, extracts figures, encodes with multilingual-e5-small, saves to SQLite.

条目附件选择规则:
- 只处理 contentType='application/pdf'（EPUB/HTML 快照暂跳过：无图注结构，收益低，长期任务）
- 排除"沉浸式翻译/双语"对照版 PDF 与明显补充材料（supplement/SI/附件）
- 一个条目挂多个 PDF 时，优先符合 "作者 X.-YYYY-标题" 主文命名惯例的 PDF
"""

import os
import re
import shutil
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
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
TEMP_DB = r"C:\Users\chmzs\.dsh\temp_zotero_indexer.sqlite"

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
        (SELECT value FROM itemDataValues v JOIN itemData d ON d.valueID = v.valueID JOIN fields f ON f.fieldID = d.fieldID WHERE d.itemID = i.itemID AND f.fieldName = 'publisher') as publisher
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

    # 作者映射：key -> ["First Last" 全名，按 orderIndex 排序]
    cursor.execute("""
        SELECT i.key, c.firstName, c.lastName, ic.orderIndex
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
        JOIN items i ON ic.itemID = i.itemID
        WHERE ct.creatorType = 'author'
        ORDER BY i.key, ic.orderIndex
    """)
    authors_map = {}
    for key, first_name, last_name, _oi in cursor.fetchall():
        f = (first_name or "").strip()
        l = (last_name or "").strip()
        full = f"{f} {l}".strip() if f else l
        if full:
            authors_map.setdefault(key, []).append(full)
    conn.close()
    try:
        os.remove(TEMP_DB)
    except Exception:
        pass

    # 按父条目聚合全部 PDF 附件
    by_item = {}
    order = []
    for r in rows:
        item_key, att_key, att_path, title, date_val, journal, journal_abbr, publisher = r
        if item_key not in by_item:
            by_item[item_key] = {
                "item_key": item_key,
                "title": title or "",
                "date_val": date_val,
                "journal": journal or "",
                "journal_abbr": (journal_abbr or "").strip(),
                "publisher": (publisher or "").strip(),
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
