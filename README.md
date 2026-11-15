# zoteo-fig-db

**地学文献图库引擎** —— 从本地 Zotero 文库的 PDF 中批量抽取学术图表原图与题注（Caption），用 granite-embedding-97m-multilingual-r2 本地语义索引（中英跨语言，384 维 / INT8 93.7MB），提供人工检索画廊 + Agent API + 多模态视觉解读闭环。

> 设计源流：Zhang J. (2025) *Small Language Models With Sentence-Level Corpus Offer Significant Potential for the Geoscience Community*, AGU *Perspectives of Earth and Space Scientists*（doi:10.1029/2025CN000283）。论文开源了句子级 MiniLM 检索范式；本项目实现其"图 ↔ 图注一一映射"的图表检索路线，并补全了论文未公开的部分：**PDF 版面级图体定位**、Obsidian/Zotero 工作流联动、视觉大模型消费闭环与 Windows 服务化。

## 核心特性

- **零 Token 本地索引**：`granite-embedding-97m-multilingual-r2`（97M 参数 / 384 维 / ONNX INT8 93.7MB，Apache-2.0，多语言 MTEB Retrieval 60.3 vs e5-small 50.9），不依赖任何云端 API
- **出版商适配器路由**：按**刊名**（非 publisher 字段）匹配 Nature/Elsevier/AGU/中文刊等图注句法；几何定位逻辑全在 base 共享
- **图体精准定位**：单幅位图直抽原始字节；矢量图取 `矢量路径 ∪ 位图 ∪ 紧邻文本标注` 并集；**题注上方无图形证据即拒绝**（防"正文当图"）；表格全程排除
- **双尺寸 WebP**：原图 ≤1600px q72（对齐视觉模型 ~1568px 有效上限）+ 480px 缩略图（画廊带宽降 ~75%）
- **面板级切分（v2.1）**：多联版面按两路线切出 `Fig. 4a/4b…` 独立行——A 文本标签严格网格（nature 实测覆盖 44%）/ B 复合位图内缝投影（elsevier 主战场，题注声明面板数为语义锚，块数≠声明数即拒切）；整图行原样保留（画廊默认视图不变），API/MCP 以 `panels=1`/`with_panels` 透传，同父多面板合并占一个检索槽位，面板独立成图独占分辨率预算
- **混合检索**：numpy 矩阵 BLAS 余弦 + FTS5 OR 关键词召回两阶段；矩阵缓存 mmap 落盘秒级冷启动；增量追加不重建
- **人工画廊**（`http://127.0.0.1:5173`，局域网可达）：无限滚动+content-visibility、灯箱原图、**一键跳 Zotero 打开 PDF 并定位页码**、复制 Obsidian 双链/图片嵌入/DSH 审图提示词
- **Agent 集成**：`/api/search` 返回图路径+题注+双链，配合 `read_image` 直接进多模态视觉循环
- **服务化**：任务管理器进程名 `zoteo-fig-db`；开始菜单一键启停；计划任务看门狗每 5 分钟自愈；网页可优雅关停（尊重手动停止标记）
- **三层工具链**：首次/大版本全库重刷用 `batch_master.py`（家族分组+断点+超时二分+隔离清单）；日常增量与卫生用计划任务 `weekly_update.py`（备份轮转→新论文入库→孤儿GC）；单篇立刻建图用 `POST /api/update {"item_keys":[...]}`

## 它需要你自己的 Zotero 库（以及一次长跑）

这个仓库**不附带任何图库**。它做的是把你自己 Zotero 里的 PDF 变成可语义检索的图库，因此第一次运行必须跑一次全量抽取。这是工具的前提，不是缺陷。开工前先看这张表，再决定值不值得：

| 项目 | 本机实测（2,249 篇 / 16,058 图） | 换算 |
| :--- | :--- | :--- |
| 首次全库抽取 | 约 8–10 小时（16 s/篇，强制重抽口径） | ≈ 0.3 小时 / 100 篇 |
| 日常增量（最近 30 篇） | 约 8 分钟 | — |
| 图片缓存磁盘占用 | 1.4 GB（≈84 KB/图，含原图 + 480px 缩略图） | ≈ 0.6 GB / 1,000 篇 |
| 索引库 | 152 MB | 随图数线性增长 |
| 模型 | 118 MB（granite-97m INT8 93.7 + tokenizer 24.1，一次性） | — |
| 画廊常驻内存 | ≈650 MB（模型 + 16,058×384 矩阵） | — |
| 网络 | 仅首次下载模型，此后全离线、零 token | — |
| 检索延迟 | 热态 p50 34 ms / p95 39 ms；冷启动载入矩阵 372 ms | 随图数近似线性 |

**什么时候不该用它**：库里只有几十篇 PDF 时，直接翻 PDF 更快；只想查几篇的图，也不必建库。它不是通用搜索，是"把我的领域文献变成图库"的一次性投资。

**跑不完怎么办**：全库抽取走 `batch_master.py`，断点可续（`batch_state.json`）；单篇异常进隔离清单，不阻塞其余篇目，中断后重跑不会从头开始。

## 快速开始（建你自己的图库）

1. **环境**：Python ≥3.10 + `pymupdf` `pillow` `numpy` `onnxruntime`（本项目用 [pixi](https://pixi.sh) geo 环境）
2. **模型**：下载 [granite-embedding-97m-multilingual-r2](https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2) 的 `onnx/model_quint8_avx2.onnx`（改名 model_int8.onnx，93.7MB）与 `tokenizer.json`（24.1MB），放到 `models/granite-97m-r2/`
3. **配置**：`indexer.py` 顶部 `ZOTERO_DIR` / `STORAGE_DIR` 指向你的 Zotero 数据目录（**这处手改是暂时的**：配置层与自动检测在途，见 Roadmap）（只读访问 `zotero.sqlite`，不写）
4. **首次建库**：`python indexer.py --limit 20` 试跑，全库用 `python batch_master.py`（断点可续）；此后交给每周计划任务即可
5. **启动画廊**：`启动 zoteo-fig-db.bat`（或 `python server.py`）；Windows 保活：
   `schtasks /Create /F /TN "zoteo-fig-db-watchdog" /SC MINUTE /MO 5 /TR "<pythonw副本> watchdog.py"`（非 Windows 可 cron 等效）

## Roadmap（在途）

- **配置层**：`config.toml` + `zoteo-fig-db setup` 自动检测 Zotero 数据目录（优先读 Zotero profile 的 `extensions.zotero.dataDir`，回退 `~/Zotero`），替代当前需手改源码的 21 处硬编码绝对路径
- **跨平台安装包**：GitHub Actions 矩阵构建 deb / rpm / dmg（arm64 + x86_64）/ Windows 安装版 + portable 版，模型内嵌，装完即用、离线可用
- **检索质量观测**：查询日志 + 零结果清单，把"调参"变成可量化对照（当前只有离线诊断脚本）

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
├── models/            # [不入库] granite-97m INT8 ONNX 权重
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
