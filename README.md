# zoteo-fig-db

**地学文献图库引擎** —— 从本地 Zotero 文库的 PDF 中批量抽取学术图表原图与题注（Caption），用 multilingual-e5-small 本地语义索引（中英跨语言），提供人工检索画廊 + Agent API + 多模态视觉解读闭环。

> 设计源流：Zhang J. (2025) *Small Language Models With Sentence-Level Corpus Offer Significant Potential for the Geoscience Community*, AGU *Perspectives of Earth and Space Scientists*（doi:10.1029/2025CN000283）。论文开源了句子级 MiniLM 检索范式；本项目实现其"图 ↔ 图注一一映射"的图表检索路线，并补全了论文未公开的部分：**PDF 版面级图体定位**、Obsidian/Zotero 工作流联动、视觉大模型消费闭环与 Windows 服务化。

## 核心特性

- **零 Token 本地索引**：`multilingual-e5-small`（ONNX INT8 仅 118MB，CPU 推理，中英与跨语言统一空间），不依赖任何云端 API
- **出版商适配器路由**：按**刊名**（非 publisher 字段）匹配 Nature/Elsevier/AGU/中文刊等图注句法；几何定位逻辑全在 base 共享
- **图体精准定位**：单幅位图直抽原始字节；矢量图取 `矢量路径 ∪ 位图 ∪ 紧邻文本标注` 并集；**题注上方无图形证据即拒绝**（防"正文当图"）；表格全程排除
- **双尺寸 WebP**：原图 ≤1600px q72（对齐视觉模型 ~1568px 有效上限）+ 480px 缩略图（画廊带宽降 ~75%）
- **面板级切分（v2.1）**：多联版面按两路线切出 `Fig. 4a/4b…` 独立行——A 文本标签严格网格（nature 实测覆盖 44%）/ B 复合位图内缝投影（elsevier 主战场，题注声明面板数为语义锚，块数≠声明数即拒切）；整图行原样保留（画廊默认视图不变），API/MCP 以 `panels=1`/`with_panels` 透传，同父多面板合并占一个检索槽位，面板独立成图独占分辨率预算
- **混合检索**：numpy 矩阵 BLAS 余弦 + FTS5 OR 关键词召回两阶段；矩阵缓存 mmap 落盘秒级冷启动；增量追加不重建
- **人工画廊**（`http://127.0.0.1:5173`，局域网可达）：无限滚动+content-visibility、灯箱原图、**一键跳 Zotero 打开 PDF 并定位页码**、复制 Obsidian 双链/图片嵌入/DSH 审图提示词
- **Agent 集成**：`/api/search` 返回图路径+题注+双链，配合 `read_image` 直接进多模态视觉循环
- **服务化**：任务管理器进程名 `zoteo-fig-db`；开始菜单一键启停；计划任务看门狗每 5 分钟自愈；网页可优雅关停（尊重手动停止标记）
- **三层工具链**：首次/大版本全库重刷用 `batch_master.py`（家族分组+断点+超时二分+隔离清单）；日常增量与卫生用计划任务 `weekly_update.py`（备份轮转→新论文入库→孤儿GC）；单篇立刻建图用 `POST /api/update {"item_keys":[...]}`

## 快速开始（建你自己的图库）

1. **环境**：Python ≥3.10 + `pymupdf` `pillow` `numpy` `onnxruntime`（本项目用 [pixi](https://pixi.sh) geo 环境）
2. **模型**：下载 [multilingual-e5-small](https://huggingface.co/onnx-community/multilingual-e5-small) 的 `onnx/model_quantized.onnx`（改名 model_int8.onnx，~118MB）与 `tokenizer.json`，放到 `models/multilingual-e5-small/`
3. **配置**：`indexer.py` 顶部 `ZOTERO_DIR` / `STORAGE_DIR` 指向你的 Zotero 数据目录（只读访问 `zotero.sqlite`，不写）
4. **首次建库**：`python indexer.py --limit 20` 试跑，全库用 `python batch_master.py`（断点可续）；此后交给每周计划任务即可
5. **启动画廊**：`启动 zoteo-fig-db.bat`（或 `python server.py`）；Windows 保活：
   `schtasks /Create /F /TN "zoteo-fig-db-watchdog" /SC MINUTE /MO 5 /TR "<pythonw副本> watchdog.py"`（非 Windows 可 cron 等效）

## Agent API
- `GET /api/search?q=&top_k≤500&offset=&journal=&year_min=&year_max=&item_key=&fig_no=&panels=` —— 语义+关键词混合检索；`item_key` 省略 `q` 即列表该篇全部图（裸键/`KEY-` 前缀/小写均可，2026-10-19 修复）；`panels=1` 透传面板行，默认仅整图
- `POST /api/search` `{"q":["批量≤50条"],"top_k":20,...}` —— 批量检索；单字符串 q 返回同 GET 的扁平数组
- `GET /api/facets` —— 期刊/家族/年份分布；`GET /image/<file>`、`/thumb/<file>` —— 原图/缩略图字节
- `POST /api/update` `{"item_keys":[...]}` —— 定向增量入库；`GET /api/shutdown` —— 停机（看门狗尊重手动标记）

## 多设备访问
服务监听 `0.0.0.0:5173`，宿主机 `GET /api/urls` 列出全部可达地址。其他设备的浏览器与 Agent 直接走 HTTP：`/api/search`（`top_k≤500`，支持 journal/年份筛选）、`/image/<file>`、`/thumb/<file>`、`/api/stats`——机器读图 = 先下载原图再喂视觉模型。连不通时检查 Windows 防火墙放行 TCP 5173 入站（仅专用网络）。

## 目录

```
zoteo-fig-db/
├── engine.py          # 抽取/编码/检索/DB（核心库）
├── family_rules.py    # 出版商家族规则单一事实源（调度分组与提取路由共用）
├── adapters/          # 出版商适配器（chinese/nature/elsevier/agu/plos/generic + 注册表按家族路由）
├── notes_index.py     # item_key→Obsidian 笔记双链映射；期刊简称合法性校验
├── indexer.py         # Zotero 扫描 + 主 PDF 优选 + 增量入库
├── server.py          # 零依赖画廊 + REST API（端口 5173）
├── batch_master.py    # 全库分批编排（家族分组/QC/断点/二分重试）— 首次建库/大版本重刷用
├── weekly_update.py   # 每周自动维护：库快照轮转 → 增量入库 → 孤儿图清理
├── batch_worker.py    # 单批执行器（逐篇 jsonl 进度 + quarantine）
├── reindex_all.py     # 算法升级后全量重抽（limit=400 仅覆盖前 400 篇，全库升级见下）
├── reindex_families.py # 族级定向重抽（清场后重提；面板 v2.1 全库升级通道，支持 all）
├── panel_qc.py        # 面板切分灰度 QC（只读干跑：叠框联系表 + report.jsonl，不写主库）
├── watchdog.py        # 看门狗（端口体检 + detached 拉起，尊重 .manual_stop）
├── weekly_update.py   # 每周自动维护：库快照轮转 → 新论文增量入库 → 孤儿图清理
├── models/            # [不入库] e5-small INT8 ONNX 权重
├── cache/             # [不入库] webp 图 + 向量矩阵磁盘缓存 + 笔记映射缓存
└── batch_tmp/         # [不入库] 批次中间产物
```

## 关键口径

- **期刊简称**：条目 `journalAbbreviation` 字段（首字母/词前缀合法性校验，拦截元数据错配脏值）→ 同刊共识 → 内置地学常用表 → 通用兜底；运行时不依赖任何 CSV
- **作者**：第一作者全名（Zotero creators 表）
- **范围**：仅 PDF；EPUB（非地学书+fitz 不出图）与 HTML 快照（题注被剥离）经实测裁定排除

## 边界与免责

- 抽取的 PDF 与图表版权属原出版商，**仅限个人研究用途**；请勿分发图库
- 数据库、图片、模型均可由源码再生，仓库只含代码

## License

MIT
