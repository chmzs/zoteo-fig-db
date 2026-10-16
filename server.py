"""
zoteo-fig-db server (gallery + API)
Zero-dependency HTTP server based on Python's built-in http.server.
Fully compatible with Python 3.10 - 3.15+.
"""

import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from engine import IMAGE_DIR, FigureDB, FigureSearcher

PORT = int(os.environ.get("GEO_FIGURE_PORT", 5173))
searcher = None
db = FigureDB()

HTML_CONTENT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>zoteo-fig-db · 地学文献图库</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent: #38bdf8;
            --accent-hover: #0ea5e9;
            --tag-bg: #0369a1;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            line-height: 1.5;
            padding: 20px;
        }
        header {
            max-width: 1400px;
            margin: 0 auto 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .title-group h1 {
            font-size: 24px;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .stats-badge {
            font-size: 13px;
            color: var(--text-secondary);
            background: #1e293b;
            padding: 4px 12px;
            border-radius: 16px;
            border: 1px solid var(--card-border);
        }
        .search-container {
            display: flex;
            gap: 12px;
            background: var(--card-bg);
            padding: 10px 16px;
            border-radius: 12px;
            border: 1px solid var(--card-border);
        }
        .search-input {
            flex: 1;
            background: transparent;
            border: none;
            color: #fff;
            font-size: 16px;
            outline: none;
        }
        .search-input::placeholder { color: #64748b; }
        .btn-search {
            background: var(--accent);
            color: #0f172a;
            border: none;
            padding: 8px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
        }
        .btn-search:hover { background: var(--accent-hover); }
        .btn-search[disabled] { opacity: 0.45; cursor: default; }
        .filter-row {
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
            font-size: 13px;
            color: var(--text-secondary);
        }
        .quick-tags {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .quick-tag {
            background: #1e293b;
            border: 1px solid var(--card-border);
            color: var(--text-secondary);
            padding: 3px 10px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 12px;
        }
        .quick-tag:hover { border-color: var(--accent); color: var(--accent); }

        .gallery {
            max-width: 1400px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
            gap: 22px;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: transform 0.2s, border-color 0.2s;
            content-visibility: auto;
            contain-intrinsic-size: auto 460px;
        }
        .card:hover {
            transform: translateY(-2px);
            border-color: var(--accent);
        }
        .card-img-wrap {
            width: 100%;
            height: 250px;
            background: #090d16;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            overflow: hidden;
            border-bottom: 1px solid var(--card-border);
        }
        .card-img-wrap img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            transition: transform 0.3s;
        }
        .card-img-wrap:hover img {
            transform: scale(1.03);
        }
        .card-body {
            padding: 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            flex: 1;
        }
        .card-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }
        .journal-badge {
            background: var(--tag-bg);
            color: #fff;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
        }
        .sim-score {
            color: var(--accent);
            font-weight: 600;
        }
        .card-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-primary);
            line-height: 1.3;
        }
        .card-fig-no {
            font-size: 13px;
            font-weight: 700;
            color: var(--accent);
        }
        .card-caption {
            font-size: 12px;
            color: var(--text-secondary);
            display: -webkit-box;
            -webkit-line-clamp: 4;
            -webkit-box-orient: vertical;
            overflow: hidden;
            line-height: 1.45;
            background: rgba(0,0,0,0.2);
            padding: 6px 8px;
            border-radius: 6px;
            border-left: 3px solid var(--accent);
        }
        .card-actions {
            margin-top: auto;
            padding-top: 10px;
            border-top: 1px solid var(--card-border);
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .btn-action {
            flex: 1 1 45%;
            padding: 6px 8px;
            font-size: 12px;
            text-align: center;
            background: #334155;
            color: #f8fafc;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            transition: 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            white-space: nowrap;
        }
        .btn-action:hover { background: #475569; }
        .btn-pdf { background: #be123c; font-weight: 600; }
        .btn-pdf:hover { background: #e11d48; }

        /* Lightbox modal */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0; top: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.92);
            backdrop-filter: blur(4px);
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal.active { display: flex; }
        .modal-content {
            max-width: 92vw;
            max-height: 92vh;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            position: relative;
        }
        .modal-img-container {
            flex: 1;
            min-height: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: auto;
        }
        .modal-img-container img {
            max-width: 100%;
            max-height: 72vh;
            object-fit: contain;
            cursor: zoom-in;
        }
        .modal-close {
            position: absolute;
            top: 12px; right: 16px;
            font-size: 24px;
            color: #94a3b8;
            cursor: pointer;
            background: none; border: none;
        }
        .modal-close:hover { color: #fff; }
        .modal-details {
            max-height: 140px;
            overflow-y: auto;
            font-size: 13px;
            color: var(--text-secondary);
            border-top: 1px solid var(--card-border);
            padding-top: 8px;
        }
        #toast {
            position: fixed;
            bottom: 26px;
            right: 26px;
            background: #0284c7;
            color: #fff;
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 13px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            opacity: 0;
            transform: translateY(8px);
            transition: opacity 0.25s, transform 0.25s;
            pointer-events: none;
            z-index: 2000;
        }
        #toast.show { opacity: 1; transform: translateY(0); }
    </style>
</head>
<body>
    <header>
        <div class="header-top">
            <div class="title-group">
                <h1>🌍 zoteo-fig-db <span style="font-size:14px;color:#94a3b8;font-weight:400;">地学文献图库</span></h1>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;">
                <div class="stats-badge" id="statsBadge">已收录 -- 张图表 (-- 篇文献)</div>
                <button class="btn-action" style="flex: none; background: #0284c7; font-weight: 600;" onclick="triggerUpdate()" id="btnUpdate" title="增量扫描 Zotero 最近入库文献并提取图表">
                    <span>🔄 增量更新</span>
                </button>
                <button class="btn-action" style="flex: none; background: #475569;" onclick="shutdownServer()" title="安全关停本地图表服务">
                    <span>⏹️ 关闭服务</span>
                </button>
            </div>
        </div>
        <div class="search-container">
            <input type="text" id="searchInput" class="search-input" placeholder="输入自然语言或关键词（例如：全新世降水对比 / lake organic carbon / Tibetan Plateau warming）..." autofocus>
            <button class="btn-search" onclick="doSearch()">搜 索</button>
        </div>
        <div class="filter-row">
            <span>快捷预设:</span>
            <div class="quick-tags">
                <span class="quick-tag" onclick="quickSearch('Holocene moisture precipitation')">全新世干湿与降水</span>
                <span class="quick-tag" onclick="quickSearch('Tibetan Plateau elevation warming')">青藏高原海拔增温</span>
                <span class="quick-tag" onclick="quickSearch('organic carbon burial lake')">湖泊有机碳埋藏</span>
                <span class="quick-tag" onclick="quickSearch('vegetation dynamics remote sensing')">遥感植被动态</span>
            </div>
        </div>
    </header>

    <main class="gallery" id="gallery"></main>
    <div id="countnote" style="text-align:center; color:#64748b; font-size:12px; padding:8px;"></div>
    <div id="morewrap" style="display:none; text-align:center; padding:10px;"><button class="btn-search" onclick="appendBatch()">↓ 加载更多</button></div>
    <div id="sentinel" style="height:1px;"></div>

    <div class="modal" id="imageModal" onclick="closeModal(event)">
        <div class="modal-content" onclick="event.stopPropagation()">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <div class="modal-img-container">
                <img id="modalImg" src="" alt="Figure">
            </div>
            <div class="modal-details">
                <div style="font-weight: bold; color: var(--accent);" id="modalFigNo"></div>
                <div style="color: #fff; margin-bottom: 4px;" id="modalTitle"></div>
                <div id="modalCaption"></div>
            </div>
        </div>
    </div>

    <div id="toast"></div>

    <script>
        let currentResults = [];
        let lastQuery = '';
        const BATCH = 24;
        let loadedCount = 0;
        let fetchTopK = 100;   // 随滚动逐轮加深: 100 -> 500
        let io = null;

        async function loadStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                document.getElementById('statsBadge').innerText = `已收录 ${data.total_figures} 张图表 (${data.total_papers} 篇文献)`;
            } catch(e) {}
        }

        async function doSearch() {
            const q = document.getElementById('searchInput').value.trim();
            if (!q) return;

            lastQuery = q;
            const gallery = document.getElementById('gallery');
            gallery.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 40px;">正在通过 e5 多语言语义检索...</div>';

            fetchTopK = 100;
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&top_k=${fetchTopK}`);
                const data = await res.json();
                currentResults = data;
                renderGallery(data);
            } catch(e) {
                gallery.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #ef4444; padding: 40px;">检索出错，请查看控制台</div>';
            }
        }

        function quickSearch(tag) {
            document.getElementById('searchInput').value = tag;
            doSearch();
        }

        document.getElementById('searchInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doSearch();
        });

        function renderGallery(items) {
            const gallery = document.getElementById('gallery');
            loadedCount = 0;
            if (!items || items.length === 0) {
                gallery.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 40px;">未找到匹配图表</div>';
                updateMoreBtn();
                return;
            }
            gallery.innerHTML = '';
            appendBatch();
        }

        function cardHtml(item, idx) {
            const fname = item.image_path.split(/[\\\\/]/).pop();
            const imgSrc = `/image/${encodeURIComponent(fname)}`;
            // 卡片只加载 480px 缩略图（~17KB）；灯箱用原图（≤1600px，对齐视觉模型有效像素上限）
            const thumbSrc = item.thumb_name ? `/thumb/${encodeURIComponent(item.thumb_name)}` : imgSrc;

            const openPdfUrl = item.att_key
                ? `zotero://open-pdf/library/items/${item.att_key}?page=${item.page_no || 1}`
                : `zotero://select/library/items/${item.item_key}`;

            const wikilinkBtn = item.wikilink
                ? `<button class="btn-action" onclick="copyField(${idx}, 'wikilink', this)" title="复制 Obsidian 双链: ${item.wikilink.replace(/"/g, '')}">
                            <span>🔗 复制笔记双链</span>
                        </button>`
                : '';

            return `
            <div class="card">
                <div class="card-img-wrap" onclick="openModal(${idx})">
                    <img src="${thumbSrc}" loading="lazy" alt="${item.fig_no}">
                </div>
                <div class="card-body">
                    <div class="card-meta">
                        <span class="journal-badge">${(item.authors ? item.authors + ' · ' : '')}${(item.journal_abbr || item.journal || 'Journal')} (${item.year || 'N/A'}) · P.${item.page_no}</span>
                        <span class="sim-score">相关度: ${(item.score * 100).toFixed(0)}%</span>
                    </div>
                    <div class="card-title">${item.title}</div>
                    <div class="card-fig-no">${item.fig_no}</div>
                    <div class="card-caption" title="${item.caption}"><strong>题注:</strong> ${item.caption}</div>
                    <div class="card-actions">
                        <a class="btn-action btn-pdf" href="${openPdfUrl}" title="在 Zotero 中直接打开 PDF 并滚动到第 ${item.page_no} 页此图">
                            <span>📄 打开 PDF 到此图</span>
                        </a>
                        ${wikilinkBtn}
                        <button class="btn-action" onclick="copyField(${idx}, 'imgembed', this)" title="复制可直接在 Obsidian 渲染的图片链接">
                            <span>🖼️ 复制图片嵌入</span>
                        </button>
                        <button class="btn-action" onclick="copyField(${idx}, 'dshprompt', this)" title="复制用于 DSH 视觉分析的提示词">
                            <span>🤖 问 DSH</span>
                        </button>
                    </div>
                </div>
            </div>
            `;
        }

        async function appendBatch() {
            const gallery = document.getElementById('gallery');
            let next = currentResults.slice(loadedCount, loadedCount + BATCH);
            if (!next.length && currentResults.length >= fetchTopK && fetchTopK < 500) {
                fetchTopK += 100;
                try {
                    const rr = await fetch(`/api/search?q=${encodeURIComponent(lastQuery)}&top_k=${fetchTopK}`);
                    currentResults = await rr.json();
                } catch(e) {}
                next = currentResults.slice(loadedCount, loadedCount + BATCH);
            }
            if (!next.length) { updateMoreBtn(); return; }
            const html = next.map((item, rel) => cardHtml(item, loadedCount + rel)).join('');
            gallery.insertAdjacentHTML('beforeend', html);
            loadedCount += next.length;
            updateMoreBtn();
        }

        function updateMoreBtn() {
            const wrap = document.getElementById('morewrap');
            const counter = document.getElementById('countnote');
            const canMore = loadedCount < currentResults.length || (currentResults.length >= fetchTopK && fetchTopK < 500);
            if (wrap) wrap.style.display = canMore ? 'block' : 'none';
            if (counter) counter.textContent = currentResults.length ? `已加载 ${loadedCount} / ${currentResults.length} 张匹配图表` : '';
        }

        // 无限滚动：哨兵进入视口前 800px 即追加下一批；DOM 由 content-visibility 跳过屏外渲染
        (function setupInfiniteScroll() {
            const sentinel = document.getElementById('sentinel');
            if (!sentinel || !('IntersectionObserver' in window)) return;
            io = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) appendBatch();
            }, { rootMargin: '800px 0px' });
            io.observe(sentinel);
        })();

        function openModal(idx) {
            const item = currentResults[idx];
            if (!item) return;
            const fname = item.image_path.split(/[\\\\/]/).pop();
            document.getElementById('modalImg').src = `/image/${encodeURIComponent(fname)}`;
            document.getElementById('modalFigNo').innerText = `${item.fig_no} (PDF 第 ${item.page_no} 页)`;
            document.getElementById('modalTitle').innerText = `${item.title} (${item.journal || ''} ${item.year || ''})`;
            document.getElementById('modalCaption').innerText = item.caption;
            document.getElementById('imageModal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('imageModal').classList.remove('active');
        }

        function showToast(msg, isError) {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.style.background = isError ? '#be123c' : '#0284c7';
            t.classList.add('show');
            setTimeout(() => t.classList.remove('show'), 2600);
        }

        async function triggerUpdate() {
            const btn = document.getElementById('btnUpdate');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span>⏳ 扫描入库中...</span>';
            btn.disabled = true;

            try {
                const res = await fetch('/api/update', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    showToast(`增量更新完成：新入库 ${data.new_figures} 张图表`);
                    loadStats();
                    doSearch();
                } else {
                    showToast('更新失败: ' + (data.message || '未知错误'), true);
                }
            } catch (e) {
                showToast('请求更新失败: ' + e, true);
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        async function shutdownServer() {
            if (!confirm('确定要关停本地 zoteo-fig-db 图库服务吗？关停后网页将无法访问。')) return;
            try {
                await fetch('/api/shutdown', { method: 'POST' });
            } catch (e) {}
            document.body.innerHTML = `
                <div style="display: flex; height: 80vh; flex-direction: column; align-items: center; justify-content: center; color: #94a3b8; font-family: sans-serif;">
                    <h2 style="color: #f8fafc; margin-bottom: 12px;">服务已成功停止</h2>
                    <p>如需重新使用，在开始菜单启动「zoteo-fig-db」即可。</p>
                </div>
            `;
        }

        function copyField(idx, field, btn) {
            const item = currentResults[idx];
            if (!item) return;
            let text = '';
            if (field === 'wikilink') {
                text = item.wikilink;
            } else if (field === 'imgembed') {
                const fname = item.image_path.split(/[\\\\/]/).pop();
                text = `![${item.fig_no}](${window.location.origin}/image/${encodeURIComponent(fname)})`;
            } else if (field === 'dshprompt') {
                const p = item.image_path.replace(/\\\\/g, '/');
                text = `请结合地学背景深度解读此图 ${p}: ${item.caption}`;
            }
            if (!text) return;
            navigator.clipboard.writeText(text).then(() => {
                if (!btn) return;
                const orig = btn.innerHTML;
                btn.innerHTML = '<span>✓ 已复制</span>';
                btn.style.background = '#16a34a';
                setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; }, 1200);
            });
        }

        // 初始不加载任何图片：避免打开网页就拉全库；等用户输入或点快捷预设
        loadStats();
        document.getElementById('gallery').innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 60px 0;">输入关键词或点击上方快捷预设，开始语义检索图表</div>';
    </script>
    <div style="text-align:center;color:#64748b;font-size:11px;padding:10px 0 16px;" id="addrbar"></div>
    <script>
        fetch('/api/urls').then(r => r.json()).then(d => {
            document.getElementById('addrbar').textContent = '访问地址：' + d.urls.join('　·　') + '　（换网络后 IP 会变，overlay 地址恒定）';
        }).catch(() => {});
    </script>
    <div id="backTop" title="回到顶部" style="position:fixed;right:18px;bottom:18px;z-index:900;display:none;width:42px;height:42px;border-radius:50%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;cursor:pointer;font-size:18px;line-height:42px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,.45);user-select:none;">↑</div>
    <script>
        window.addEventListener('scroll', () => {
            document.getElementById('backTop').style.display = window.scrollY > 700 ? 'block' : 'none';
        }, { passive: true });
        document.getElementById('backTop').addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    </script>
</body>
</html>
"""


class ZoteoFigHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
            return

        elif path == "/api/stats":
            stats = db.get_stats()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/urls":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"urls": reachable_urls()}, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/search":
            global searcher
            if searcher is None:
                searcher = FigureSearcher()

            q = query.get("q", [""])[0]
            top_k = max(1, min(500, int(query.get("top_k", [20])[0])))
            journal = query.get("journal", [None])[0]
            year_min = query.get("year_min", [None])[0]
            year_max = query.get("year_max", [None])[0]

            results = searcher.search(
                query=q,
                top_k=top_k,
                journal_filter=journal,
                year_min=year_min,
                year_max=year_max,
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))
            return

        elif path.startswith("/image/") or path.startswith("/thumb/"):
            prefix = "/image/" if path.startswith("/image/") else "/thumb/"
            fname = urllib.parse.unquote(path[len(prefix):])
            fname = os.path.basename(fname)
            if prefix == "/thumb/" and not fname.endswith(".thumb.webp"):
                self.send_response(404)
                self.end_headers()
                return
            img_path = os.path.join(IMAGE_DIR, fname)
            if os.path.exists(img_path):
                ext = os.path.splitext(fname)[1].lower()
                mime = "image/webp"
                if ext == ".png":
                    mime = "image/png"
                elif ext in [".jpg", ".jpeg"]:
                    mime = "image/jpeg"

                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                with open(img_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/update":
            try:
                from indexer import get_zotero_items_with_pdfs, index_papers
                # Scan recent 30 papers
                papers = get_zotero_items_with_pdfs(limit=30)
                before_stats = db.get_stats()
                index_papers(papers, force_reindex=False)
                after_stats = db.get_stats()
                new_figs = after_stats["total_figures"] - before_stats["total_figures"]
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "new_figures": new_figs}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/shutdown":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "Server shutting down..."}, ensure_ascii=False).encode("utf-8"))
            # 写入手动停止标记：看门狗 5 分钟检查时将尊重该标记不再自动拉起
            try:
                open(os.path.join(BASE_DIR, ".manual_stop"), "w").close()
            except Exception:
                pass
            
            # Asynchronously shutdown the server
            def killer():
                time.sleep(0.5)
                os._exit(0)
            import threading
            threading.Thread(target=killer).start()
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def reachable_urls():
    """本机全部可访问地址：回环 + 各网卡 IPv4（含 WLAN 与 xedTun 等 overlay）。"""
    urls = [f"http://127.0.0.1:{PORT}"]
    try:
        import socket
        for ip in sorted(set(socket.gethostbyname_ex(socket.gethostname())[2])):
            if not ip.startswith("127.") and ip != "0.0.0.0":
                urls.append(f"http://{ip}:{PORT}")
    except Exception:
        pass
    return urls


def run():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadingHTTPServer(server_address, ZoteoFigHandler)
    print(f"zoteo-fig-db running at http://0.0.0.0:{PORT}")
    for u in reachable_urls():
        print(f"  reachable: {u}")

    # Auto-open browser when port is ready
    if os.environ.get("NO_BROWSER", "0") != "1":
        def open_browser():
            time.sleep(0.3)
            try:
                import webbrowser
                webbrowser.open(f"http://127.0.0.1:{PORT}")
            except Exception:
                pass
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    # 后台预热：只构建服务端内存缓存（向量矩阵+笔记映射），不向浏览器发送任何图片
    def warm_caches():
        global searcher
        try:
            time.sleep(0.5)
            if searcher is None:
                searcher = FigureSearcher()
            searcher._ensure_cache()
            import notes_index
            notes_index.get_notes_map()
        except Exception:
            pass

    import threading
    threading.Thread(target=warm_caches, daemon=True).start()

    httpd.serve_forever()


if __name__ == "__main__":
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        in_use = (s.connect_ex(("127.0.0.1", PORT)) == 0)

    if in_use:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        sys.exit(0)

    run()
