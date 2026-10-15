# AGENTS.md — zoteo-fig-db 项目 Agent 文档

## 品牌规范（用户可见面一律用此名）

进程名 `zoteo-fig-db.exe`（pythonw 副本，位于 pixi geo 环境根）· 开始菜单 `zoteo-fig-db.lnk` · 计划任务 `zoteo-fig-db-watchdog` · 界面标题 `zoteo-fig-db · 地学文献图库` · 启停脚本 `启动/停止 zoteo-fig-db.bat`。目录名 `D:\Zotero\fig_db` 为历史路径，代码内以 `BASE_DIR` 相对解析，整体搬家仅需改硬编码绝对路径：`indexer.py(ZOTERO_DIR/TEMP_DB)`、`watchdog.py(PYDIR)`、`启动 zoteo-fig-db.bat`、计划任务 TR、`server.py` 无（端口 env 可控）。

## 不变量（改动前必读）

1. **图↔题注契约**：一切检索基于题注文本（MiniLM）+ FTS5。定位原则**宁宽勿裁，但绝不盲裁**——`adapters/base.locate_figure_box`：位图单幅直抽原始字节；矢量取路径∪位图∪6pt 内文本标注并集；**题注上方无图形证据→拒绝该候选**（防正文交叉引用/合并块假题注，2026-10-16 实测教训：Elsevier 双栏"图注并入正文块+整栏盲裁"会产出纯文字假图卡）。
2. **路由只认刊名**：`adapters/__init__.get_adapter(journal, doc)`，期刊条目 publisher 字段 83% 为空，禁止依赖；新增出版商=在 `adapters/` 加文件 + 注册表加一行，`engine.py` 零改动。
3. **单写者**：worker/master 串行写 sqlite；画廊 server 只读。矩阵缓存签名 `(count, MAX(indexed_at), MAX(id))` 自动失效；UPDATE 元数据列需连带 bump indexed_at 或删除 `cache/embed_*`。
4. **去重**：DB `UNIQUE(item_key, fig_no)` + 检索侧 (title,fig_no) 去重；多条目同题（预印本/正式版并存）由后者兜住。
5. **简称链**：`notes_index.zot_abbr_plausible` 校验字段值（首字母子序列/词前缀），孤证怪值不可采信；中文刊保持原名；单词刊不加点。
6. **服务生命周期**：`/api/shutdown` 写 `.manual_stop`（看门狗尊重），`启动 zoteo-fig-db.bat` 清标记；看门狗带 `NO_BROWSER=1`，用户手动启动才弹浏览器。

## 常用操作

```bash
PY=D:/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe
$PY indexer.py --limit 30                  # 增量入库（多PDF条目自动选主文，排除双语对照/SI）
$PY indexer.py --journal GRL --force       # 按刊强制重抽
$PY batch_master.py                        # 全库分批（断点续跑：batch_state.json / FINAL_DONE.json）
$PY reindex_all.py                         # 算法版本升级后全量重抽
NO_BROWSER=1 $PY server.py                 # 画廊（默认 5173，0.0.0.0 局域网可达）
```

夜间批次 QC 判据（batch.log 每行 OK 记录）：`zero/papers>40%` 或 `extreme` 异常 → 查该家族 `batch_tmp/<fam>_<i>.papers.jsonl` 与 quarantine，必要时改适配器后 `DELETE FROM figures WHERE item_key IN(该家族)` 重跑。

## 已知坑（勿重踩）

- `innerHTML +=` 重建节点 → 图片全部重新请求；用 `insertAdjacentHTML`
- pythonw 副本必须放环境根目录（同级 python315.dll + Lib 相对定位）
- Git Bash 里 PowerShell 的 `$_` 必须 `\$_` 转义；`/tmp` Windows python 不认
- `edit` 工具 new/old_string 顺序要盯三遍（本会话多次翻车）；改共享 .ps1/.bat 注意编码
- fitz 对 EPUB 只出文字流不出图；期刊 HTML 快照图是 dataURI 但题注被剥离——两者均**实测裁定不做**
- 位图收集用 `get_image_info(xrefs=True)` 拿宽高，勿逐图 `extract_image` 预解码（3 倍速差）

## 同步与版本

- 远端 `github.com/chmzs/zoteo-fig-db`；`cache/ models/ batch_tmp/ *.sqlite* *.log batch_state.json .manual_stop` 均不入库（可再生）
- 换机部署：clone → 放回 README 步骤 1-2（环境+模型）→ 配路径 → 首跑

## 当前任务交接

夜跑状态看 `batch.log` 尾部 + `FINAL_DONE.json`（存在即完成）；隔离清单 `batch_state.json.quarantined`。完成后流程：重启 zoteo-fig-db 服务 → 抽样 read_image 目检 → 出中文总结报告。
