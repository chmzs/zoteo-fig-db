# WORKORDER — 面板级切分恢复（2026-10-18）

状态：**已完成（2026-10-19, commit e642eaa）**。§三 双路线（标签网格+位图内缝投影）落地；§四 验收通过但样本口径三处与 PDF 实际不符（Fig.4 实为 (a)(b) 两面板；UJ5TQUQP 单幅箱线被门禁正确拒切；97LJ8KDF 面板路线不可达）——详见 DEVELOPMENT_LOG §7.5。遗留三项决断（全库 v2.1 重抽/family_rules 缺口/band over-capture 修复）见 HANDOFF.md。

## 一、背景与证据（为什么恢复你曾取消的面板切分）

2026-10-18 PaperBell 三页合成审计实战（湖泊水位/植被/温度）给出三组实测：

1. 查看端有硬顶：模型经 read_image 或 MCP 图像流看任何图，都被重采样到长边 ≤1280px JPEG。多联版面共享这份预算 → 单面板实得 ~600–700px，轴刻度字号 3–4px，数值级判读失效。
2. 压缩率不是杠杆：塔若错 Fig.4 实测 q72→q85 重编码，Laplacian 方差逐位相同（清晰度零变化），体积 +17%。
3. 提高整图上限对模型也无增益：同页 fitz 整页渲染 1600/2400/2800 分别为 0.25/0.44/0.54MB，但整图入模型仍被压回 1280，面板分辨率一个字节不变；唯一受益方是网页画廊人眼与客户端裁窗。

成员实战代价：PIL 手工裁带一次返工（撞 axis 标签带）、箱线图盲读、数值断言被迫全部回退 pdftotext 复核（读图纪律已固化进 zotero-figure 技能）。结论：直接提升面板级分辨率的唯一手段是子面板独立预算（抽取 ≤1600 原生 + 查看 1280 独享），即恢复面板切分。存储与检索代价远低于全库取消上限。

## 二、目标与范围

1. 面板检测回归 adapters：定位 (a)(b)(c)(d) 子面板 bbox，每面板独立成 figures 行（fig_no 追加字母，如 Fig. 4a），panels_json 列已预留（现全 NULL）存 bbox/父子溯源，schema 细节自定。
2. 整图行保留不变（画廊默认视图与既有 UNIQUE(item_key, fig_no) 语义不动）；面板行带 origin 标记（如 extractor_version 后缀或独立列），支持 `DELETE WHERE origin='panel'` 一键回退，老缓存零破坏。
3. engine.CURRENT_EXTRACTOR_VERSION 2.0 → 2.1；全库定向重抽走既有夜间无人值守通道（weekly_update / finish_run / batch_master，单写者不变量），白天不碰服务。规模 15,053 图 / 2,228 篇 → 预计行数 35k–45k，仍在 <10 万免向量库红线内，FTS5 与 mmap 矩阵签名机制自动失效重建。
4. 首波家族限定 elsevier / agu / nature（多联图重灾区且有图形证据链可守）；chinese/generic 双栏混排易误切，只出整图，等误切率数据说话再扩。
5. mcp_server.py：search_figures 与 get_figure_image/list_paper_figures 透传面板行；同父多面板默认合并返回（top_k 槽位不霸屏），with_panels=False 可关闭。
6. 顺手修确认 bug：/api/search 的 item_key 过滤与 DB 裸 8 位键口径错配（传 KEY-XXXX 与裸键均实测返回空，fig_db 实战靠 sqlite 只读绕）；以 JYGMPNRM 为验收样本。

## 三、设计决策点（开工先定）

- 面板边界算法：候选 label 锚（"(a)" 文本位 + 矢量/位图路径聚类对齐）/ 空白投影（行列为零切分）/ 混合。建议混合，且必须过不变量 1 的门：无图形证据 → 拒切该候选，宁宽勿裁、绝不盲裁。
- caption 策略：面板无独立题注文本则继承父题注 + "（面板 a）"前缀，保证 e5 检索命中父题注语义同时不制造四条同文重复霸屏（FTS 侧配 fig_no 区分）。
- 误切率门槛：首批 50 篇 elsevier/agu 灰度，人工目视复核误切率 <5% 再全量夜抽。

## 四、验收标准（三张实测问题图必须全过）

1. JYGMPNRM（塔若错 CATENA）Fig. 4a–d 独立成行、单面板长边 ≤1600 原生；
2. 97LJ8KDF（纳木错）Fig. 2 年代模型面板；UJ5TQUQP（NETP）Fig. 2 箱线面板同理；
3. MCP 路径：list_paper_figures('JYGMPNRM') 与 search_figures('塔若错 湖面', item_key=...) 返回面板行，模型侧 1280 = 满面板分辨率；
4. 去重链复核：UNIQUE(item_key, fig_no) 与检索侧 (title, fig_no) 不吞面板行；
5. 回退演练：DELETE origin='panel' 后全库回到 15,053 行、画廊与 MCP 行为与今日一致。

## 五、文档补课（非本工程但同批做）

0a. ✅ 已办（2026-10-19 00:05 lead 代办入库）：`mcp_server.py` 与 `watchdog.py` 双端口改动已审（py_compile 过、无敏感串）并按明确路径 commit，接盘会话无需再做。
本会话新增且项目三件套（AGENTS/README/HANDOFF）零记载的资产，开工时一并补一段：
- mcp_server.py（FastMCP，streamable-http 0.0.0.0:23122 /mcp，宿主机 192.168.0.102，远程机 192.168.0.100 直连，图像经 base64 内联绕过文件边界）；
- watchdog.py 已扩为双端口看顾（5173 + 23122，.manual_stop 同时停两服务）；
- 消费端契约在 ~/.agents/skills/zotero-figure/SKILL.md（含读图纪律：视觉判读只取结构信息，数值断言必须文字复核——面板落地后此条仍是最后防线，不要移除）。

## 六、挂账（本工单不做，记录在案）

- Kramer 2010 仅入库 4 图（Fig 3/5/7 缺，抽取覆盖问题非面板问题）；
- figures.context_text 实测为空（图文共读链断，只靠 caption）；
- 面板级切分若稳定，可评估把画廊卡片默认从整图切到面板网格（UI 决策，留用户）。

## 七、验证入口（沿用 HANDOFF 一键验证 + 面板增量）

```bash
cd /d/Zotero/fig_db
curl -s http://127.0.0.1:5173/api/stats
curl -s "http://127.0.0.1:5173/api/search?q=Taro+Co&item_key=JYGMPNRM&top_k=10"   # bug 修复验收
# 面板验收：返回中应出现 Fig. 4a–d；MCP 侧 list_paper_figures('JYGMPNRM')
```
