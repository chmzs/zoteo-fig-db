# 开发与测试经验档案 — zoteo-fig-db

> 本文记录本项目开发/调试中**验证过的**经验与教训（决策依据、翻车现场、测试方法）。
> 使用方式见 README，行为约束见 AGENTS.md，热状态见 HANDOFF.md，agent 操作手册见 ~/.agents/skills/zotero-figure/SKILL.md。

## 1. 抽取器（PDF → 图）

**1.1 按刊名路由，不按出版商。** 库里 83% 条目 publisher 字段为空；刊名永远在。家族规则的单一事实源是 `family_rules.py`（JOURNAL_RULES/EXACT_FAMILY/journal_family），适配器与统计共用，改一处即可。出版商缩写（如 WGSN→AGU）用 `resolve_abbr` 归一。

**1.2 几何定位：宁宽勿裁，但要拒绝而非盲裁。** `adapters/base.locate_figure_box` 三向证据：位图原始字节直抽（不走渲染）、矢量取"路径∪位图∪邻近文本标注"并集、题注上方无任何图形证据 → 拒绝该候选。血泪教训：Elsevier 双栏"图注并入正文块"场景曾整栏盲裁，产出纯文字假图卡。

**1.3 页眉污染用硬地板，不用特征围堵。** AGU 页眉 logo（矢量小字形簇 y40-61）+ DOI 行会通过三种路径渗入图框：证据并集、跨边界矩形（y0<64<y1）、文本标注合并。曾尝试按尺寸过滤小字形、链式聚类隔离——全被绕（刻度线与 logo 尺寸重叠、聚类 gap 桥接）。最终方案是一行确定性规则：**clip 顶 ≥64pt**（期刊页眉带恒 <62）+ band_dr 排除 y1≤64 + header_guard 标注守卫。教训：对抗性围堵不如语义层硬规则。

**1.4 题注编号是三代演化，别一次想到底。**
- v1.7：行级救援（题注与正文同行 merged line，Annual Reviews）——判据用"后续句是否大写开头/数字/括号"区分题注起始 vs 正文引用（"Figure 2 shows" 必须拒）
- v1.9：字母编号 `Figure S1`；PLOS 用**数字后句点**判据区分题注（"Fig 3."）与正文引用（"Fig 3 presented"），13 篇零图全救活
- v2.0：词式编号 `Supplementary Figure 12`/`Extended Data Figure 3`（Nature Communications SI 实测用词式，8→34 图）
- 陷阱实录：加前缀时放非捕获组 → `matched_str=m.group(1)` 丢前缀 → "Supplementary Figure 1" 与正文 "Figure 1" 在 UNIQUE(item_key,fig_no) 下**静默撞车**。修复=外层捕获整条 + `m.group(0)` + rstrip 分隔符。**动捕获组编号前必须先 grep 所有 m.group(N) 引用点；同一条正则被 nature 适配器独立复刻了一份——改基类正则必须 grep 全 adapters 找分身。**

**1.5 拼接 PDF 与页数上限联动。** 用户习惯把 SI 拼接进正文 PDF（PassportPDF 等工具重编码）。改正则（S 编号）而不放开页数上限=白改。120 页上限的成本：全库重提 612 篇候选仅 ~55 分钟。

**1.6 版本戳 = 行为语义的唯一标识。** `CURRENT_EXTRACTOR_VERSION` 在 engine 单点定义、所有写入路径引用，禁止散落硬编码（曾有三处 "1.1" 导致统计不可信）。发布版本号（git tag v1.0）与抽取器戳是两回事，混淆过一次。

## 2. 嵌入模型选型（MiniLM → e5-small）

**2.1 决策路径**：约束 <200MB → 候选 multilingual-e5-small(118MB INT8, MIT) / IBM Granite-R2-97M(fp32 390MB 超标) / GeeVec(110MB GPL 无量化) / Zhinao(无 ONNX)。MiniLM 时代中文查询实测废（词表英文为主，中文全 [UNK]，靠 FTS 兜底）。**e5 胜出**：预算内唯一带中英统一空间 + 社区量化成熟（onnx-community INT8 可直接跑）。

**2.2 量化导出验收：黄金矩阵已知答案测试。** Granite 社区 int8 导出实锤坍缩（任意文本对 cos≈0.999），fp16 拒载（rotary Cast 类型错），只有 fp32 正确——用 fp32 对拍 20 篇已知相似对，int8 复现不了即判导出不可信。**换模型前永远先跑黄金矩阵，再跑 A/B 并排（ab_report*.txt 有模板），最后人工裁决**——e5 与 Granite top-5 一致率仅 27%，20 条查询人工判 e5 中文组更净，分差（MTEB +9.4）在小样本上不可见。

**2.3 tokenizers 库直接吃 HF tokenizer.json**（Unigram 25 万词条也不用手写解码），e5 还需 `token_type_ids=zeros`（Xenova 导出要求缺则报错）、query:/passage: 前缀、mean-pool+mask、L2。384 维不变 → 矩阵缓存 shape 兼容，切换成本集中在重嵌入（全库 ~25 分钟）。

## 3. 服务与 API

**3.1 零依赖 http.server 撑到 1.4 万图无压力**；启动预热检索器（首查 3.2s → 0.28s）；矩阵缓存按 (count,max_id,max_indexed_at) 签名失效，写路径免费感知变更。

**3.2 地址自适应**：服务绑 0.0.0.0，`/api/urls` 枚举本机全部可达 IP（127.0.0.1 恒在 + WLAN/overlay），前端页脚自答——换网络零配置。个人 IP 只进私有文档（SKILL），公开 README 只写机制。跨设备首选 xedTun overlay 地址（恒定），WLAN IP 仅同路由兜底。

**3.3 三层工具链定位（用户问"临时产物?"的正确答法）**：`batch_master.py`=首次建库/大版本全库重刷（家族分组+断点+超时二分+隔离清单）；`weekly_update.py`+计划任务=日常（备份轮转→变更检测→增量→GC）；`POST /api/update {"item_keys":[...]}`=agent 立刻建图/改 PDF 后重提（已入库走清场 redo）。变更检测=mtime>该篇 MAX(indexed_at)+120s（epoch 列让对比零成本）。

**3.4 API 演进由真实需求驱动**：100 条上限其实是前端写死（引擎无上限）→ 改翻页加深 100→500；批量 POST、item_key/fig_no 过滤、offset、/api/facets、FTS 召回 200→600 都是本轮"哪些是需要的"讨论后落地，每项有实测用例（9 项测试套件全绿才算完）。布尔查询语法/服务端排序/token 鉴权：明确暂缓并记录理由。

## 4. 运维与 Windows 特有坑

**4.1 进程与命名**：pythonw 克隆改名 `zoteo-fig-db.exe` 必须放环境根目录（python3xx.dll 相对定位）；看门狗=计划任务 5min + `.manual_stop` 标记尊重手动停机；批量重提期间**先停画廊**（长读事务与写锁互撞是 database is locked 的主因）。

**4.2 sqlite 并发**：`timeout=30`（默认 5s 对 4-6 线程写者不够）；外部内容 FTS5 不能直接 DELETE 主表不清 fts（remove_item 模式：DELETE fts rowid try/except → DELETE 主表 → 删文件）。

**4.3 pixi 红线**：`pixi global install` 会整环境重解（真实事故：py3.15→3.14 + conda numpy BLAS 崩 + python315.dll 消失 → 克隆 exe 悬空 + matmul 静默死）。修复=pip force-reinstall numpy + 重克隆 exe。**动包后必测：matmul + exe 起得来。**

**4.4 输出丢失三连**：`python -c` 无 `-u` 崩溃时缓冲全丢（假"无输出"）；Git Bash `/tmp` Windows python 不认；bash 单条 sleep>110s 被 120s 硬超时杀（长等待拆段或用 timeoutMs）。本 harness 并行 bash 常丢 description 参数（全会话 10+ 次），补救=单条重试并显式带 description。

**4.5 PowerShell 5.1**：`$_` 在 bash 双引号里会被展开成上一命令参数（`$_`→`supfig_scan.log` 灾难现场），必写 `\$_`；系统内存吃紧时 Get-Format/Out-String 会 800705af OOM——排查命令要轻量降级（tasklist/ps -W）。

**4.6 git 纪律**：`git add -A` 在脏工作目录=埋雷（真实事故：54MB sqlite.bak 被并行提交推上公开仓）。修复三步曲：rm --cached + amend + **tag 也要迁移强推**。公共仓库不放个人 IP/私有状态文件（HANDOFF/NIGHT_REPORT 已移出版本控制）。并行提交两条命令写同一仓库=竞态（本会话 engine.py 被两条链同时动过，锚点全乱）——**git 写操作永远串行单调用**。

## 5. 测试与验收方法论

- **计数回归**：改动前后固定样本集（多栏中文 ZSMFVDNS=6 / PLOS=11 / Copernicus=4 / AGU=7 / D&D=2）零漂移才算过
- **目检条带**：crop 顶/底 230px 读图验证页眉/页脚残留（比断言可靠）
- **全库扫描器先行**：任何"影响哪些文献"的问题不拍脑袋——scan_si/supfig/poison_scan 三个逐页探查脚本，输出 targets.json 供定向重提；扫描器自身也要容错（毒页 break 记录、不可开文件单独归类）
- **API 改动必带 curl 测试套件**（T1-T9 全绿再 commit）
- **断点续跑**：长任务每 200 条落 checkpoint（重启只补差额），链尾用 DONE 哨兵串接下一步
- 默认值陷阱：`stamp.get(k, '2.0')` 把零行文献全跳过——**哨兵默认值必须落在"会被处理"的一侧**（改 '0.0'）
- 模型切换/网络闪断时段的工具输出**不可信**：本档曾有三批"看似成功"的补丁实际未落盘（grep 现场=唯一裁判）；被打断的长链尾进程要用 targets 重算+排除已完成戳来幂等续跑
- PowerShell 管道里匹配 bash 自身命令行会**自杀**（`-match 'chain_supfig'` 命中当前执行体）——先 `Get-Process` 列 PID 再按 PID 精确杀

## 6. 数字档案（2026-10-16 实测）

夜间全库 4h49m（2221 篇）；重刷速率 ~6-8 篇/分（6 线程，SI/长 PDF 重样本）；检索首查 3.2s→预热后 0.28s；GC 清孤儿 20407 文件/478MB；词式 SI 修复单篇 8→34 图；当前库 14,524 图 / 2,227 篇（v2.0 戳重提进行中）。

## 7. 面板级切分 v2.1（2026-10-19 实测）

**7.1 前提被实测推翻，双路线重建。** 工单假设面板字母 (a)(b) 在文本层可抓——41 篇/323 父图实测：elsevier 父图文本层≥2 字母率 **1.8%**（97LJ8KDF 的两个 `a` 实为表格 14C 上标拆 span 误捕），nature 反之 **44.4%**（矢量标注）。Elsevier 复合图的面板字母**烧死在位图像素里**。故定双路线：A 标签严格网格（nature 型）/ B 位图内空白投影（elsevier 主战场）——即工单§三"建议混合"，但适用面数据是实测才见的。教训：验收样本写进工单前先跑扫描脚本探查。

**7.2 路线 B 的语义锚=题注声明面板数。** 位图内部唯一第二证据是题注 "(a)…(b)…" 分句。相对极小值缝递归切（缝墨量≤0.22×块 p90；两侧≥12% 墨量防削色标/图例）→ 块数与声明数不等时按缝强度塌缩（同缝两子块恰铺满父框，塌缩=精确无重叠）→ 仍不等或字母不从 'a' 连续 → 整组拒切。血泪：run1（无连续门）16 父图/41 面板中 4 父图字母错配（题注有 (b) 面板却写成别样→排序映射必错）；加门后 run2 12 父图/28 面板，目视误切 **0/28**（<5% 门槛）。"缺口 a,c,d,e,f" 是门禁的真阳性样本。

**7.3 分辨率增益低于工单论证，实质价值在归属。** 28 面板实测：面板原生长边 vs 整图入模实得，增益**中位 x1.00**、>x1.2 仅 29%（结构天花板=存储 1600→查看 1280=x1.25；父图原生≤1280 零增益；满幅竖排面板如 JYGMPNRM Fig.4 仅 x1.02-1.07）。工单§一"多联共享预算"论证只对 **≥2 列且原生>1600** 的大复合图成立。面板化真正收益：①每面板独立行+独立分句题注（检索归属——查"水深重建"不再命中整张混图）；②修复历史漏提/over-capture 的入口。汇报禁写"分辨率翻倍"。

**7.4 版本重提必须先清场（灰度踩实）。** `indexer --force` 不清旧行：v1.7 带换行 `Fig.\n1` 与 v2.1 `Fig. 1` 在 UNIQUE 下不同键并存 → 25 重复行。补救=归一化（去全部非字母数字）比对、只删"存在 2.1 等价行"的旧行（KEEP=0 保证零丢失），文件交 `weekly_update.orphan_gc()` 引用反查（清 406 文件/9MB）。正通道=`reindex_families.py`（先 DELETE 行+删图再提）。`reindex_all.py` 的 `limit=400` 只覆盖前 400 篇、其余静默留旧行——历史缺陷挂账，全库升级勿用它。

**7.5 验收三样本与 PDF 实际的偏差（工单§四）。** JYGMPNRM Fig.4 题注只声明 (a)(b) 两面板（工单写 a–d）→ 切 4a/4b 通过；UJ5TQUQP Fig.2 系单幅箱线（"sites ordered by latitude"，题注无面板段）→ 门禁拒切=正确行为；97LJ8KDF 路由 generic（SAGE 不在首波）且版式=上表格+下 700×358 位图（原生低于 1280 上限，切了零增益）→ **该验收项面板路线不可达**，后续验收样本应以 nature 多联矢量图为代表。回退演练：删 28 面板行→15,061 整图行，检索行为与今日一致 ✓。
