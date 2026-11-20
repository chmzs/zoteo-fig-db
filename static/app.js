// @ts-check

// getElementById 的集中断言：页面结构固定，元素必然存在；集中一处换取调用点清爽。
// 注意：DOM 属性名因此不做编译期校验，本文件类型检查的价值在 **数据契约**（SearchItem/JobState）。
/** @param {string} id @returns {any} */
function byId(id) {
    return document.getElementById(id);   // 必须是原生调用：批量替换曾把它改成 byId(id) → 无限递归
}
/** @type {SearchItem[]} */
let currentResults = [];
let lastQuery = '';
const BATCH = 24;
let loadedCount = 0;
let fetchTopK = 100;   // 随滚动逐轮加深: 100 -> 500
let io = null;
const MAX_RESULTS = 500;    // 与服务端 top_k 夹取上限一致
let fetchingMore = false;   // 哨兵连续触发时防止并发分页
let poolExhausted = false;  // 服务端候选池取尽 → 隐藏"加载更多"
let moreBtnIdleHtml = null;  // "加载更多"按钮的常态内容（含 SVG），首次加载时缓存

// HTML 转义：卡片全部走 innerHTML 拼接，题注/标题/作者里的 & " < 必须转义，
// 否则 title="..." 属性被引号截断 → 整卡错版（2026-11-15 审计）
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
        (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
}

async function loadStats(retries = 6) {
    // 失败重试：服务刚起时可能仍在加载向量矩阵，旧实现静默失败会让
    // 徽标永久停在 “已收录 -- 张图表”（2026-10-28 用户截图实测）
    for (let i = 0; i < retries; i++) {
        try {
            const res = await fetch('/api/stats');
            const data = await res.json();
            if (typeof data.total_figures === 'number') {
                byId('statsBadge').innerText =
                    `已收录 ${data.total_figures} 张图表 (${data.total_papers} 篇文献)`;
                return;
            }
        } catch (e) {}
        await new Promise(r => setTimeout(r, 700));
    }
    byId('statsBadge').innerText = '统计加载失败（服务可能仍在启动）';
}

// ---- 结构化过滤（作者/期刊/年份）：与语义 q 正交叠加，不做开关 ----
function filterParams() {
    const p = [];
    const a = byId('fAuthor').value.trim();
    const j = byId('fJournal').value;
    const y1 = byId('fYearMin').value;
    const y2 = byId('fYearMax').value;
    if (a) p.push('author=' + encodeURIComponent(a));
    if (j) p.push('journal=' + encodeURIComponent(j) + '&journal_exact=1');
    if (y1) p.push('year_min=' + y1);
    if (y2) p.push('year_max=' + y2);
    const st = byId('fStar').value;
    if (st) p.push('star_min=' + st);
    const keys = byId('fItemKeys').value.trim();
    if (keys) p.push('item_key=' + encodeURIComponent(keys));
    return p.length ? '&' + p.join('&') : '';
}
function clearFilters() {
    byId('fAuthor').value = '';
    byId('fJournal').value = '';
    byId('fYearMin').value = '';
    byId('fYearMax').value = '';
    byId('fStar').value = '';
    byId('fItemKeys').value = '';
    byId('countnote').textContent = '';
    doSearch();
}
async function setStar(idx, n, e) {
    if (e && e.stopPropagation) e.stopPropagation();
    const item = currentResults[idx];
    if (!item) return;
    // 点已点亮的同一颗星 = 清除评分
    const next = (item.rating === n) ? 0 : n;
    try {
        const res = await fetch('/api/rate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({item_key: item.item_key, fig_no: item.fig_no, stars: next}),
        });
        const data = await res.json();
        if (data.status !== 'ok') throw new Error(data.message || '评分写入失败');
        item.rating = data.stars;
        refreshStars(idx);
    } catch (err) {
        console.error('setStar failed:', err);
    }
}
function refreshStars(idx) {
    const item = currentResults[idx];
    const box = document.querySelector('.card-stars[data-idx="' + idx + '"]');
    if (!item || !box) return;
    box.querySelectorAll('.star').forEach((el, k) => {
        const on = (item.rating || 0) >= k + 1;
        el.classList.toggle('on', on);
        el.setAttribute('aria-pressed', String(on));
    });
    const label = box.querySelector('.star-label');
    if (label) label.textContent = item.rating ? item.rating + ' 星' : '';
}
async function loadJournalOptions() {
    try {
        const res = await fetch('/api/facets');
        const data = await res.json();
        const sel = byId('fJournal');
        (data.journals || []).forEach(([j, n]) => {
            const o = document.createElement('option');
            o.value = j; o.textContent = j + ' (' + n + ')';
            sel.appendChild(o);
        });
    } catch(e) {}
}

// ---- 快捷预设：服务端 sidecar（presets.json），跨设备一致 ----
/** @type {Preset[]} */
let presets = [];
let presetEditMode = false;
let editingPresetIndex = -1;

async function loadPresets() {
    try {
        const res = await fetch('/api/presets');
        const data = await res.json();
        presets = Array.isArray(data.presets) ? data.presets : [];
    } catch (e) {
        presets = [];
    }
    renderPresets();
}

function renderPresets() {
    const box = byId('quickTags');
    if (!box) return;
    box.innerHTML = '';
    presets.forEach((preset, index) => {
        const tag = document.createElement('button');
        tag.type = 'button';
        tag.className = 'quick-tag';
        if (presetEditMode) {
            tag.innerHTML = '<span class="tag-text">' + esc(preset.label) + '</span>'
                + '<span class="tag-del" title="删除">✕</span>';
            tag.title = '点击修改检索词：' + preset.query;
            tag.onclick = (event) => {
                const target = /** @type {HTMLElement} */ (event.target);
                if (target && target.classList.contains('tag-del')) {
                    deletePreset(index);
                } else {
                    beginEditPreset(index);
                }
            };
        } else {
            tag.textContent = preset.label;
            tag.title = preset.query;
            tag.onclick = () => quickSearch(preset.query || preset.label);
        }
        box.appendChild(tag);
    });
    if (presetEditMode && presets.length < 20) {
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'quick-tag';
        addBtn.textContent = '＋ 新增';
        addBtn.onclick = () => beginEditPreset(-1);
        box.appendChild(addBtn);
    }
    const editBtn = byId('btnPresetEdit');
    if (editBtn) editBtn.textContent = presetEditMode ? '✓ 完成' : '⚙️ 编辑';
}

function togglePresetEdit() {
    presetEditMode = !presetEditMode;
    if (!presetEditMode) cancelPresetEdit();
    renderPresets();
}

function beginEditPreset(index) {
    editingPresetIndex = index;
    const preset = index >= 0 ? presets[index] : { label: '', query: '' };
    byId('presetLabel').value = preset.label || '';
    byId('presetQuery').value = index >= 0 ? (preset.query || '') : '';
    byId('presetForm').style.display = 'flex';
    byId('presetHint').textContent =
        index >= 0 ? '正在修改：' + preset.label : '新增预设（最多 20 条）';
    byId('presetLabel').focus();
}

function cancelPresetEdit() {
    editingPresetIndex = -1;
    const form = byId('presetForm');
    if (form) form.style.display = 'none';
    const hint = byId('presetHint');
    if (hint) hint.textContent = '';
}

async function savePreset() {
    const label = (byId('presetLabel').value || '').trim();
    const query = (byId('presetQuery').value || '').trim();
    const hint = byId('presetHint');
    if (!label) {
        hint.textContent = '显示名不能为空';
        return;
    }
    const next = presets.map((preset) => ({ label: preset.label, query: preset.query }));
    if (editingPresetIndex >= 0) {
        if (next.some((preset, i) => i !== editingPresetIndex && preset.label === label)) {
            hint.textContent = '显示名重复：' + label;
            return;
        }
        next[editingPresetIndex] = { label: label, query: query || label };
    } else {
        if (next.length >= 20) {
            hint.textContent = '最多 20 条';
            return;
        }
        if (next.some((preset) => preset.label === label)) {
            hint.textContent = '显示名重复：' + label;
            return;
        }
        next.push({ label: label, query: query || label });
    }
    await persistPresets(next, editingPresetIndex >= 0 ? '已修改预设' : '已新增预设');
}

async function deletePreset(index) {
    const target = presets[index];
    if (!target) return;
    if (!confirm('删除预设「' + target.label + '」？')) return;
    await persistPresets(presets.filter((preset, i) => i !== index), '已删除预设');
}

async function persistPresets(next, okMessage) {
    const hint = byId('presetHint');
    try {
        const res = await fetch('/api/presets', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({presets: next}),
        });
        const data = await res.json();
        if (!res.ok || data.status !== 'ok') throw new Error(data.message || ('HTTP ' + res.status));
        presets = Array.isArray(data.presets) ? data.presets : next;
        cancelPresetEdit();
        renderPresets();
        showToast(okMessage);
    } catch (e) {
        if (hint) hint.textContent = '保存失败：' + ((e && e.message) || e);
    }
}

async function doSearch() {
    const q = byId('searchInput').value.trim();
    const fp = filterParams();
    if (!q && !fp) return;

    lastQuery = q;
    const gallery = byId('gallery');
    const keysRaw = byId('fItemKeys').value.trim();
    // 按 KEY 列图不是相似度排序，分数恒为 0：隐藏相关度徽标，避免误读
    byId('gallery').classList.toggle('no-score', Boolean(keysRaw));
    gallery.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 40px;">'
        + (keysRaw ? '正在按 Item Key 列出图表…' : '正在通过 granite 语义检索…') + '</div>';

    const DISPLAY_LIMIT = 100;
    // 多取 1 条当哨兵：存在第 101 条即说明结果被截断（比"已显示 100"精确，也不靠猜）
    fetchTopK = DISPLAY_LIMIT + 1;
    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&top_k=${fetchTopK}${fp}`);
        if (!res.ok) {
            // 服务端 500 会回 {"error":..., "message":...}，必须把它显示出来而不是只说"看控制台"
            const body = await res.text().catch(() => '');
            throw new Error('HTTP ' + res.status + ' ' + body.slice(0, 400));
        }
        const data = await res.json();
        const truncated = data.length > DISPLAY_LIMIT;
        const rows = truncated ? data.slice(0, DISPLAY_LIMIT) : data;
        currentResults = rows;
        renderGallery(rows);
        if (keysRaw) {
            const want = keysRaw.split(/[;,，；]+/).filter(Boolean)
                .map((s) => s.replace(/^KEY-/i, '').toUpperCase());
            const got = new Set(data.map((it) => (it.item_key || '').toUpperCase()));
            const miss = want.filter((k) => !got.has(k));
            byId('countnote').textContent = 'Item Key：' + got.size + ' 篇命中，共 ' + rows.length + ' 张图'
                + (miss.length ? '；未命中 ' + miss.join(', ') : '')
                + (truncated ? '；超过 ' + DISPLAY_LIMIT + ' 张已截断' : '');
        } else {
            const papers = new Set(rows.map((it) => it.item_key)).size;
            byId('countnote').textContent = truncated
                ? '命中超过 ' + DISPLAY_LIMIT + ' 张图，已显示前 ' + DISPLAY_LIMIT
                    + '（' + papers + ' 篇）；加条件缩小范围可看全'
                : '共 ' + rows.length + ' 张图 / ' + papers + ' 篇';
        }
    } catch(e) {
        const detail = (e && e.message) ? e.message : String(e);
        console.error('search failed:', e);
        gallery.innerHTML =
            '<div style="grid-column: 1/-1; color: #ef4444; padding: 32px 20px;">'
            + '<div style="text-align:center; margin-bottom:10px;">检索失败：服务未响应或服务端报错</div>'
            + '<pre id="searchErrBox" style="white-space:pre-wrap; word-break:break-all; background:#1e293b;'
            + ' border:1px solid #334155; border-radius:8px; padding:12px; font-size:12px; color:#fca5a5;'
            + ' user-select:text; cursor:text; margin:0;">' + esc(detail) + '</pre>'
            + '<div style="text-align:center; margin-top:8px; font-size:12px; color:#94a3b8;">'
            + '上面这段可直接选中复制；完整堆栈按 F12 → Console；服务端错误另存 cache/server.log</div>'
            + '</div>';
    }
}

function quickSearch(tag) {
    byId('searchInput').value = tag;
    doSearch();
}

byId('searchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
});

/** @param {SearchItem[]} items */
function renderGallery(items) {
    const gallery = byId('gallery');
    loadedCount = 0;
    poolExhausted = false;
    if (!items || items.length === 0) {
        gallery.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 40px;">未找到匹配图表</div>';
        updateMoreBtn();
        return;
    }
    gallery.innerHTML = '';
    appendBatch();
}

/**
 * @param {SearchItem} item
 * @param {number} idx
 * @returns {string}
 */
function cardHtml(item, idx) {
    const fname = item.image_path.split(/[\\/]/).pop();
    const imgSrc = `/image/${encodeURIComponent(fname)}`;
    // 卡片只加载 480px 缩略图（~17KB）；灯箱用原图（≤1600px，对齐视觉模型有效像素上限）
    const thumbSrc = item.thumb_name ? `/thumb/${encodeURIComponent(item.thumb_name)}` : imgSrc;

    const openPdfUrl = item.att_key
        ? `zotero://open-pdf/library/items/${item.att_key}?page=${item.page_no || 1}`
        : `zotero://select/library/items/${item.item_key}`;

    // 原文网页：Zotero 的 url 字段（DOI 回退在入库侧拼好），没有就不显示
    const webBtn = item.url
        ? `<a class="btn-action" href="${esc(item.url)}" target="_blank" rel="noopener" title="打开原文网页（来自 Zotero 网址字段）">
                    <span>🌐 原文网页</span>
                </a>`
        : '';
    // 在 Obsidian 打开：obsidian://open 协议，file= 用 vault 相对路径
    const noteBtn = item.obsidian_uri
        ? `<a class="btn-action" href="${esc(item.obsidian_uri)}" title="在 Obsidian 中打开对应的文献笔记">
                    <span>📝 在 Obsidian 打开</span>
                </a>`
        : '';

    const wikilinkBtn = item.wikilink
        ? `<button class="btn-action" onclick="copyField(${idx}, 'wikilink', this, event)" title="复制 Obsidian 双链: ${esc(item.wikilink)}">
                    <span>🔗 复制笔记双链</span>
                </button>`
        : '';

    return `
    <div class="card">
        <div class="card-img-wrap" role="button" tabindex="0"
             onclick="openModal(${idx})"
             onkeydown="if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openModal(${idx}); }">
            <img src="${thumbSrc}" loading="lazy" decoding="async" fetchpriority="low" alt="${esc(item.fig_no)} 图">
        </div>
        <div class="card-body">
            <div class="card-meta">
                <span class="journal-badge">${(item.authors ? esc(item.authors) + ' · ' : '')}<em class="venue">${esc(item.journal_abbr || item.journal || 'Journal')}</em> (${esc(item.year || 'N/A')}) · P.${esc(item.page_no)}</span>
                <span class="sim-score">相关度: ${Math.min(100, Math.round((item.semantic_sim ?? item.score ?? 0) * 100))}%</span>
            </div>
            <div class="card-title">${esc(item.title)}</div>
            <div class="card-fig-row">
                <span class="card-fig-no">${esc(item.fig_no)}</span>
                <span class="card-stars" data-idx="${idx}" onclick="event.stopPropagation()">
                    ${[1, 2, 3, 4, 5].map(n => `<button type="button" class="star${(item.rating || 0) >= n ? ' on' : ''}" onclick="setStar(${idx}, ${n}, event)" title="${n} 星（再点同一星清除）" aria-label="${n} 星" aria-pressed="${(item.rating || 0) >= n}">★</button>`).join('')}
                    <span class="star-label">${item.rating ? item.rating + ' 星' : ''}</span>
                </span>
            </div>
            <div class="card-caption" title="${esc(item.caption)}"><strong>题注:</strong> ${esc(item.caption)}</div>
            <div class="card-actions" onclick="event.stopPropagation()">
                <a class="btn-action btn-pdf" href="${openPdfUrl}" onclick="openZoteroProtocol(event, '${openPdfUrl}')" title="在 Zotero 中直接打开 PDF 并滚动到第 ${item.page_no} 页此图">
                    <span>📄 打开 PDF 到此图</span>
                </a>
                ${webBtn}
                ${noteBtn}
                ${wikilinkBtn}
                <button class="btn-action" onclick="copyField(${idx}, 'imgembed', this, event)" title="复制可直接在 Obsidian 渲染的图片链接">
                    <span>🖼️ 复制图片嵌入</span>
                </button>
                <button class="btn-action" onclick="copyField(${idx}, 'dshprompt', this, event)" title="复制用于 DSH 视觉分析的提示词">
                    <span>🤖 问 DSH</span>
                </button>
            </div>
        </div>
    </div>
    `;
}

async function appendBatch() {
    const gallery = byId('gallery');
    const moreBtn = /** @type {HTMLButtonElement|null} */ (document.querySelector('#morewrap button'));
    if (fetchingMore) return;   // 并发保护：哨兵与手动点击可能同时触发
    let next = currentResults.slice(loadedCount, loadedCount + BATCH);
    if (!next.length && !poolExhausted && loadedCount < MAX_RESULTS) {
        // 增量分页：offset 只取下一段。旧实现每加深一档就 top_k+=100 从 0 重算，
        // 500 上限下等于 5 次全量 e5 编码 + 全矩阵 matmul（2026-11-15 审计）
        fetchingMore = true;
        if (moreBtn) {
            // 首次进入加载态时缓存原始内容，退出时原样还原（避免在 JS 里重复一份 SVG）
            if (moreBtnIdleHtml === null) moreBtnIdleHtml = moreBtn.innerHTML;
            moreBtn.disabled = true;
            moreBtn.innerHTML = '<span class="more-spinner"></span><span>加载中…</span>';
        }
        try {
            // 30s 超时：增量入库期间 sqlite 写锁会让检索请求长时间挂住，
            // 无超时则 fetchingMore 永久为真 → 之后点按钮全部静默 return（2026-11-15 症状）
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 30000);
            let more = null;
            try {
                const rr = await fetch(`/api/search?q=${encodeURIComponent(lastQuery)}`
                    + `&top_k=${BATCH}&offset=${loadedCount}${filterParams()}`,
                    { signal: controller.signal });
                more = await rr.json();
            } finally {
                clearTimeout(timer);
            }
            if (Array.isArray(more)) {
                const seen = new Set(currentResults.map((it) => it.id + '|' + it.fig_no));
                let added = 0;
                more.forEach((it) => {
                    const key = it.id + '|' + it.fig_no;
                    if (!seen.has(key)) { seen.add(key); currentResults.push(it); added += 1; }
                });
                // 取回的条目全被去重挡住 → offset 不再前进，必须停，否则死循环
                if (added === 0 || more.length < BATCH) poolExhausted = true;
            } else {
                poolExhausted = true;
            }
        } catch (e) {
            // 失败 ≠ 取尽：报错可见、按钮保留、允许重试（旧实现静默置 poolExhausted，
            // 一次网络抖动就永久关掉分页）
            const reason = (e && e.name === 'AbortError') ? '请求超时（30s）' : ((e && e.message) || e);
            showToast('加载更多失败：' + reason, true);
        } finally {
            fetchingMore = false;
            if (moreBtn) {
                moreBtn.disabled = false;
                if (moreBtnIdleHtml !== null) moreBtn.innerHTML = moreBtnIdleHtml;
            }
        }
        next = currentResults.slice(loadedCount, loadedCount + BATCH);
    }
    if (!next.length) { updateMoreBtn(); return; }
    const html = next.map((item, rel) => cardHtml(item, loadedCount + rel)).join('');
    gallery.insertAdjacentHTML('beforeend', html);
    loadedCount += next.length;
    updateMoreBtn();
}

function updateMoreBtn() {
    const wrap = byId('morewrap');
    const counter = byId('countnote');
    const canMore = !poolExhausted && loadedCount > 0 && loadedCount < MAX_RESULTS;
    if (wrap) wrap.style.display = canMore ? 'block' : 'none';
    if (counter) counter.textContent = loadedCount ? `已加载 ${loadedCount} 张匹配图表` : '';
}

// 无限滚动：哨兵进入视口前 800px 即追加下一批；DOM 由 content-visibility 跳过屏外渲染
(function setupInfiniteScroll() {
    const sentinel = byId('sentinel');
    if (!sentinel || !('IntersectionObserver' in window)) return;
    io = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) appendBatch();
    }, { rootMargin: '800px 0px' });
    io.observe(sentinel);
})();

function openModal(idx) {
    const item = currentResults[idx];
    if (!item) return;
    resetZoom();
    const fname = item.image_path.split(/[\\/]/).pop();
    byId('modalImg').src = `/image/${encodeURIComponent(fname)}`;
    byId('modalFigNo').innerText = `${item.fig_no} (PDF 第 ${item.page_no} 页)`;
    // 元数据合并一行：作者 · 期刊全称（斜体）· 年份
    // 模态框横向空间充足，期刊优先全称；卡片窄栏仍用 journal_abbr
    // 期刊名走 <em>，故此处用 innerHTML：authors/venue 必须转义
    // esc() 已在脚本头部定义，模态框与卡片共用同一份转义
    const metaBits = [];
    if (item.authors) metaBits.push(esc(item.authors));
    const venueFull = item.journal || item.journal_abbr || '';
    if (venueFull) metaBits.push('<em class="venue">' + esc(venueFull) + '</em>');
    if (item.year) metaBits.push(esc(String(item.year)));
    byId('modalMeta').innerHTML = metaBits.join(' · ');
    byId('modalTitle').innerText = item.title;
    byId('modalCaption').innerText = item.caption;
    const dlg = byId('imageModal');
    if (!dlg.open) dlg.showModal();
}

function closeModal(e) {
    const dlg = byId('imageModal');
    // 点击遮罩时事件目标就是 <dialog> 本身；内容区已 stopPropagation
    if (e && e.type === 'click' && e.target !== dlg) return;
    if (dlg.open) dlg.close();
}

// 平台关闭（Esc / close()）后复位缩放，避免下次打开带着旧位移
byId('imageModal').addEventListener('close', resetZoom);

let zoomScale = 1;
let panX = 0, panY = 0;
let isPanning = false;
let startX = 0, startY = 0;
let hasMoved = false;

function updateTransform(smooth = false) {
    const img = byId('modalImg');
    if (!img) return;
    img.style.transition = smooth ? 'transform 0.16s cubic-bezier(0.2, 0, 0.2, 1)' : 'none';
    if (zoomScale <= 1.01) {
        zoomScale = 1;
        panX = 0;
        panY = 0;
        img.style.transform = 'none';
        img.style.cursor = 'zoom-in';
    } else {
        img.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
        img.style.cursor = isPanning ? 'grabbing' : 'grab';
    }
}

function resetZoom() {
    zoomScale = 1;
    panX = 0;
    panY = 0;
    isPanning = false;
    hasMoved = false;
    updateTransform(false);
}

(function setupZoom() {
    const container = document.querySelector('.modal-img-container');
    const img = byId('modalImg');
    if (!container || !img) return;

    img.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        hasMoved = false;
        if (zoomScale > 1) {
            isPanning = true;
            startX = e.clientX - panX;
            startY = e.clientY - panY;
            img.style.cursor = 'grabbing';
            e.preventDefault();
        }
    });

    window.addEventListener('mousemove', (e) => {
        if (!isPanning) return;
        hasMoved = true;
        panX = e.clientX - startX;
        panY = e.clientY - startY;
        updateTransform(false);
    });

    window.addEventListener('mouseup', () => {
        if (isPanning) {
            isPanning = false;
            updateTransform(false);
        }
    });

    img.addEventListener('click', (e) => {
        if (hasMoved) return; // 用户在拖拽平移，不触发缩放切换
        if (zoomScale <= 1.01) {
            const rect = img.getBoundingClientRect();
            const offsetX = e.clientX - (rect.left + rect.width / 2);
            const offsetY = e.clientY - (rect.top + rect.height / 2);
            zoomScale = 2.4;
            panX = -offsetX * (zoomScale - 1);
            panY = -offsetY * (zoomScale - 1);
            updateTransform(true);
        } else {
            resetZoom();
        }
    });

    container.addEventListener('wheel', /** @param {WheelEvent} e */ (e) => {
        const modal = byId('imageModal');
        if (!modal || !modal.open) return;
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.25 : 0.8;
        const newScale = Math.max(1, Math.min(8, zoomScale * factor));
        if (newScale <= 1.01) {
            resetZoom();
            return;
        }
        const rect = img.getBoundingClientRect();
        const mouseX = e.clientX - (rect.left + rect.width / 2);
        const mouseY = e.clientY - (rect.top + rect.height / 2);
        const scaleRatio = newScale / zoomScale;
        panX = mouseX - (mouseX - panX) * scaleRatio;
        panY = mouseY - (mouseY - panY) * scaleRatio;
        zoomScale = newScale;
        updateTransform(false);
    }, { passive: false });
})();

function showToast(msg, isError) {
    const t = byId('toast');
    t.textContent = msg;
    t.style.background = isError ? '#be123c' : '#0284c7';
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2600);
}

// ---- 索引进度：服务端 job 模型 + 1s 轮询（真实 done/total，不用批次号）----
/** @type {number|null} */
let jobTimer = null;

/** @param {JobState} job */
function renderJob(job) {
    const bar = byId('jobBar');
    const fill = byId('jobFill');
    const text = byId('jobText');
    const btn = byId('btnUpdate');
    if (!bar || !job) return;
    const total = job.total || 0;
    const done = job.done || 0;
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    const busy = job.stage === 'queued' || job.stage === 'scanning' || job.stage === 'extracting';
    bar.style.display = 'flex';
    bar.classList.toggle('is-error', job.stage === 'error');
    bar.classList.toggle('is-done', job.stage === 'done');
    fill.style.width = (job.stage === 'done' ? 100 : Math.max(pct, job.stage === 'scanning' ? 3 : 0)) + '%';
    const parts = [];
    if (job.stage === 'queued') parts.push('排队中');
    else if (job.stage === 'scanning') parts.push('扫描 Zotero 库…');
    else if (job.stage === 'extracting') parts.push(done + '/' + total + ' 篇 · ' + pct + '%');
    else if (job.stage === 'done') parts.push(job.message || '完成');
    else if (job.stage === 'error') parts.push('失败：' + (job.message || '未知错误'));
    else parts.push(job.message || job.stage || '');
    if (busy && job.current) parts.push(job.current);
    if (job.mode) parts.push('（' + job.mode + '）');
    text.textContent = parts.join(' · ');
    if (btn) {
        btn.disabled = busy;
        btn.textContent = busy ? (pct > 0 ? '更新中 ' + pct + '%' : '更新中…') : '🔄 增量更新';
    }
}

/** @param {string} jobId */
async function pollJob(jobId) {
    try {
        const res = await fetch('/api/jobs/' + encodeURIComponent(jobId));
        if (!res.ok) return;
        const job = await res.json();
        renderJob(job);
        if (job.stage === 'done' || job.stage === 'error') {
            if (jobTimer) { clearInterval(jobTimer); jobTimer = null; }
            if (job.stage === 'done') {
                showToast(job.message || '更新完成');
                loadStats();
                doSearch();
            } else {
                showToast('更新失败：' + (job.message || ''), true);
            }
        }
    } catch (e) {
        // 服务短暂不可达时保持轮询
    }
}

async function triggerUpdate() {
    const btn = byId('btnUpdate');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/jobs/index', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || !data.job_id) throw new Error(data.message || ('HTTP ' + res.status));
        if (jobTimer) clearInterval(jobTimer);
        jobTimer = setInterval(() => pollJob(data.job_id), 1000);
        pollJob(data.job_id);
    } catch (e) {
        if (btn) btn.disabled = false;
        showToast('无法启动更新：' + ((e && e.message) || e), true);
    }
}

// 页面刷新后若仍有任务在跑，自动接上进度
(async function resumeJob() {
    try {
        const res = await fetch('/api/jobs/latest');
        if (!res.ok) return;
        const job = await res.json();
        if (!job || !job.id) return;
        if (job.stage === 'done' || job.stage === 'error') return;
        if (jobTimer) clearInterval(jobTimer);
        jobTimer = setInterval(() => pollJob(job.id), 1000);
        renderJob(job);
    } catch (e) {}
})();

async function shutdownServer() {
    if (!confirm('确定要关停本地 zoteo-fig-db 图库服务吗？关停后网页将无法访问。')) return;
    const btn = byId('btnShutdown');
    if (btn) btn.innerHTML = '<span>⏳ 正在停止...</span>';
    try {
        await fetch('/api/shutdown', { method: 'POST' });
    } catch (e) {}
    // 尝试同时停止远端关联进程（如果有），并替换当前页面展示
    document.body.innerHTML = `
        <div style="display: flex; height: 80vh; flex-direction: column; align-items: center; justify-content: center; color: #94a3b8; font-family: sans-serif;">
            <h2 style="color: #f8fafc; margin-bottom: 12px;">服务已成功停止</h2>
            <p>后台服务已关停，写入 .manual_stop 防自启标记。如需重新使用，在开始菜单启动「zoteo-fig-db」即可。</p>
        </div>
    `;
}

function openZoteroProtocol(e, url) {
    e.preventDefault();
    e.stopPropagation();
    let ifr = byId('protocolIframe');
    if (!ifr) {
        ifr = document.createElement('iframe');
        ifr.id = 'protocolIframe';
        ifr.style.display = 'none';
        document.body.appendChild(ifr);
    }
    ifr.src = url;
}

function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            ta.style.top = '-9999px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const successful = document.execCommand('copy');
            document.body.removeChild(ta);
            if (successful) resolve();
            else reject(new Error('execCommand failed'));
        } catch (err) {
            reject(err);
        }
    });
}

function copyField(idx, field, btn, e) {
    if (e && e.stopPropagation) e.stopPropagation();
    const item = currentResults[idx];
    if (!item) return;
    let text = '';
    if (field === 'wikilink') {
        text = item.wikilink;
    } else if (field === 'imgembed') {
        const fname = item.image_path.split(/[\\/]/).pop();
        text = `![${item.fig_no}](${window.location.origin}/image/${encodeURIComponent(fname)})`;
    } else if (field === 'dshprompt') {
        const p = item.image_path.replace(/\\/g, '/');
        text = `请结合地学背景深度解读此图 ${p}: ${item.caption}`;
    }
    if (!text) return;
    copyToClipboard(text).then(() => {
        if (!btn) return;
        const orig = btn.innerHTML;
        btn.innerHTML = '<span>✓ 已复制</span>';
        btn.style.background = '#16a34a';
        setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; }, 1200);
    }).catch(() => {
        if (!btn) return;
        const orig = btn.innerHTML;
        btn.innerHTML = '<span>⚠️ 复制失败</span>';
        btn.style.background = '#e11d48';
        setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; }, 1500);
    });
}

// 初始不加载任何图片：避免打开网页就拉全库；等用户输入或点快捷预设
loadStats();
loadJournalOptions();
loadPresets();
byId('gallery').innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 60px 0;">输入关键词或点击上方快捷预设，开始语义检索图表</div>';

fetch('/api/urls').then(r => r.json()).then(d => {
    byId('addrbar').textContent = '访问地址：' + d.urls.join('　·　') + '　（本机用 127.0.0.1，跨设备用 overlay 恒定地址）';
}).catch(() => {});

(function setupBackTop() {
    const backTop = byId('backTop');
    if (!backTop) return;
    const sync = () => backTop.classList.toggle('show', window.scrollY > 700);
    window.addEventListener('scroll', sync, { passive: true });
    backTop.addEventListener('click', () => {
        // 系统开了"减弱动效"就别做平滑滚动
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
    });
    sync();
})();
