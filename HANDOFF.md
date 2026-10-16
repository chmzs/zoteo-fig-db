# HANDOFF — zoteo-fig-db（覆盖写，勿追加）

## 停滞断点（2026-10-16 11:20）
- **任务**：Granite-embedding-97m-multilingual-r2 INT8 切换（用户已批准，收益=中文/跨语言检索，MTEB-ML 60.3 vs e5-small 50.9）。模型文件已下载、`validate_granite.py`(GraniteEncoder: tokenizers+CLS+L2) 已写，**卡在分词→推理链路崩溃，未跑通**。
- 分词本身已验证 OK：EN/JA/ZH `unk=0`、BOS=179934、EOS=179938。
- 崩溃点：`q @ p.T` 矩阵乘静默死进程 → **pixi 装 tokenizers 触发环境重解（py3.15→3.14.8）致 numpy2.5.4 conda 构建 BLAS 损坏**；pip 强制重装 numpy 已修复（MATMUL_OK），但 `validate_granite.py` 在修复后**尚未重跑**（会话多次被截断）。
- 附带 damage 已修：画廊服务已重启（stats 12995/2212 ✓、检索 ✓）；`zoteo-fig-db.exe` 已按新 pythonw 重克隆；旧 GeoFigureServer.exe 删除；reindex_families 596/596 完成；night 批次 FINAL_DONE ✓。

## 一键验证
```
cd /d/Zotero/fig_db
"/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe" -u validate_granite.py   # 期望 GOLDEN: PASS（diag≥0.8 且行最大，卡称 0.8869/0.9577/0.9112）
curl -s http://127.0.0.1:5173/api/stats                                               # 服务活着
grep REINDEX_FAMILIES_DONE reindex_families.log                                        # 后台批完成
```

## 下一步原子动作
1. 跑上面 validate：GOLDEN PASS → 写 `ab_granite.py`（全库 12995 caption Granite 编码入缓存 + 20 查询[10中10英]与 MiniLM top5 并排对比）→ 交用户目检定夺是否切换；切换=新 encoder + 全库重嵌入（~20min）+ bump extractor_version。
2. 若 validate 仍 rc=127 无输出：`-u` 与 `python -X faulthandler` 重跑取证，重点查 onnxruntime 1.31 与 numpy2.5 pip 构建 ABI。

## 试错黑名单（严禁重踩）
- **pixi global install 任何包都可能重解 geo 环境**（本次 py3.15→3.14 + BLAS 损坏 + python315.dll 消失 → pythonw 克隆 exe 全悬空）。装前备份 `pixi global list`，装后必测 `matmul` + exe 可启动。
- `python -c` 崩溃丢缓冲输出＝假"无输出"；诊断脚本一律 `-u` 或 stderr 打印。
- Windows python 不认 Git-Bash `/tmp`；bash 单条 sleep>110s 会被 120s 超时杀（要等就拆多次或用 timeoutMs）。
- PowerShell 串里 `$_` 要 `\$_`；FTS5 external-content 禁直接 DELETE（try/except+rebuild）。
- 未经用户同意不改 engine.py 主编码器（先 A/B）。

## 关键文件
- `engine.py`(v1.7 抽取/MiniLM/检索) `adapters/`(6 族路由+family_rules) `server.py`(0.0.0.0:5173)
- `models/granite-embedding-97m-multilingual-r2/`(model_int8.onnx 97.9MB+tokenizer.json)
- `validate_granite.py`(待跑通) · `reindex_families.py`(完成) · `finish_run.py`(收尾链)
- GitHub: chmzs/zoteo-fig-db（代码已推，models/cache 不入库）· 看门狗计划任务 `zoteo-fig-db-watchdog`
