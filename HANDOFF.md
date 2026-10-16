# HANDOFF — zoteo-fig-db（覆盖写，勿追加）

## 停滞断点（2026-10-16 13:48）
- **正在跑**：AGU 家族重跑 `reindex_families.py agu_wiley`（82 篇，日志 `reindex_agu2.log`，第 1 次在 73/82 死于 `database is locked`，已停画廊服务重跑，约 13:56 完成，PID 查询 `reindex_families`）。目的：把 v1.8「页眉硬地板 y≥64 + band_dr 排 y1≤64 + header_guard 标注」落入 AGU 存量（用户投诉 logo/DOI 页眉与正文混入图体，ZBS8JUZV Fig2 实证修复后 1531→1057px 顶干净）。
- **重跑完成后待办**：①重启画廊（`NO_BROWSER=1 nohup zoteo-fig-db.exe server.py`）；②目检 `ZBS8JUZV` DB 内 Figure 2 应为 ver=1.8 且顶条无页眉；③本卡片改写为"无事/新断点"。
- e5-small INT8 嵌入后端**已切换完成**（`engine.Encoder`，MiniLM 零残留，旧向量备份 `zotero-figures.sqlite.minilm-bak`；A/B 三报告 `ab_report*.txt`，Granite↔e5 一致率 27% 但人工判 e5 中文组更净，故弃 Granite——其社区 int8 导出坍缩/fp16 拒载/390MB 超标）。

## 一键验证
```bash
cd /d/Zotero/fig_db
grep REINDEX_FAMILIES_DONE reindex_agu2.log                                   # 重跑完成标志
curl -s "http://127.0.0.1:5173/api/stats"                                     # 服务+规模
curl -s "http://127.0.0.1:5173/api/search?q=%E5%85%A8%E6%96%B0%E4%B8%96&top_k=3" | head -c 300  # 中文语义检索
```

## 试错黑名单（严禁重踩）
- **pixi global install 任何包会重解 geo 环境**（py3.15→3.14、numpy/BLAS 静默崩、python315.dll 消失→克隆 exe 悬空）。装前想清楚；现环境 3.14.8 全链路已验证，勿动。
- `python -c`/管道吞缓冲输出＝假"无输出"；诊断一律 `-u`。Git Bash `/tmp` Windows python 不认。
- 4 线程 sqlite 并发写需 `busy_timeout=30`（已入 engine.get_conn）；重跑批量期间**停画廊**避免读锁竞争。
- Granite 类新架构模型的社区 int8/fp16 导出不可信（量化坍缩实锤），要必须自量化+黄金矩阵验收。
- edit 工具 new/old 参数顺序盯三遍；heredoc 里 `''` 双单引号=空串陷阱（chinese.py 事故）。

## 下一步原子动作
1. `tail -f` 等 DONE → 起服务 → `read_image` ZBS8JUZV Fig2 顶条复核 → git 收尾。
2. 用户若报其他家族页眉混入：`reindex_families.py copernicus`（Biogeosciences 的 clip.y0=40.9 同症状，97 图/13 篇待重跑——**已发现未处理**）。

## 关键状态
- DB：~13008 图 / 2212+ 篇，e5 向量 100%；服务 PID：重跑完成后新起；看门狗任务 `zoteo-fig-db-watchdog` 武装。
- 地址：本机/Agent 恒 127.0.0.1:5173；跨设备 overlay 100.64.0.10:5173（`/api/urls` 自答）；检索深度前端 100→500 自适应，API 上限 500。
- 远端：github.com/chmzs/zoteo-fig-db 已同步（13:47）。
