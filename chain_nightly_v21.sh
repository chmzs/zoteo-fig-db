#!/bin/bash
# chain_nightly_v21.sh — §八.1 夜跑链：三家族 v2.1 重抽（家族粒度 DONE 哨兵，幂等可续跑）
# 用法: nohup bash chain_nightly_v21.sh > batch_tmp/chain_nightly.log 2>&1 &
cd /d/Zotero/fig_db || exit 1
PY="D:/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe"

echo "[chain] $(date '+%F %T') start"

# 1. 停画廊 + 无条件落 .manual_stop（画廊若本已停，shutdown 不会写标记，
#    watchdog 5 分钟内会复活 MCP 成为夜跑期读者——必须显式盖章）
curl -s -m 5 "http://127.0.0.1:5173/api/shutdown" && echo "[chain] gallery shutdown ok" || echo "[chain] gallery already down"
touch .manual_stop
echo "[chain] .manual_stop set"
sleep 3

# 2. 停 MCP 23122 读者（按 PID 精确杀，禁按脚本名串杀——黑名单）
MCP_PID=$(netstat -ano | grep LISTENING | grep ':23122 ' | awk '{print $5}' | head -1)
if [ -n "$MCP_PID" ]; then
  taskkill //PID "$MCP_PID" //F >/dev/null 2>&1 && echo "[chain] mcp $MCP_PID killed"
fi
sleep 2

# 3. 逐家族重抽（reindex_families：清场行+图文件后重提，天然幂等）
for FAM in elsevier agu_wiley nature_portfolio; do
  if [ -f "batch_tmp/NIGHT_DONE_${FAM}.json" ]; then
    echo "[chain] skip ${FAM} (done)"
    continue
  fi
  echo "[chain] $(date '+%F %T') reindex ${FAM}"
  "$PY" -u reindex_families.py "$FAM" > "batch_tmp/reindex_${FAM}.log" 2>&1
  RC=$?
  if [ $RC -eq 0 ]; then
    echo "{\"family\":\"$FAM\",\"ts\":\"$(date -Iseconds)\"}" > "batch_tmp/NIGHT_DONE_${FAM}.json"
    echo "[chain] $(date '+%F %T') ${FAM} DONE"
  else
    echo "[chain] ${FAM} FAILED rc=$RC — 中止，查 batch_tmp/reindex_${FAM}.log"
    exit 1
  fi
done

# 4. 行数核对
"$PY" -u - <<'EOF'
import sqlite3
c = sqlite3.connect("file:zotero-figures.sqlite?mode=ro", uri=True)
tot, pan, pap = c.execute("SELECT COUNT(*), SUM(origin='panel'), COUNT(DISTINCT item_key) FROM figures").fetchone()
v = c.execute("SELECT COUNT(*) FROM figures WHERE extractor_version='2.1'").fetchone()[0]
stale = c.execute("SELECT COUNT(*) FROM figures WHERE extractor_version<>'2.1'").fetchone()[0]
print(f"[chain] DB 总行={tot} 面板={pan or 0} 篇={pap} v2.1={v} 旧版残留={stale}")
EOF

# 4b. 夜跑后库备份（gitignore 内；供回退与取证）
cp -p zotero-figures.sqlite batch_tmp/night_v21.sqlite && echo "[chain] db backup ok"

# 4c. 面板复核门禁（§八.3）：三家族 dry-run 全扫 + 客观指标；超阈自动回退面板行
for FAM in elsevier agu_wiley nature_portfolio; do
  "$PY" -u panel_qc.py --family "$FAM" --limit 600 \
    --out "batch_tmp/panel_qc_night_${FAM}" > "batch_tmp/qc_night_${FAM}.log" 2>&1 \
    && echo "[chain] qc ${FAM} ok" || echo "[chain] qc ${FAM} FAILED(容错继续判)"
done
"$PY" -u panel_gate.py
GATE=$?
if [ $GATE -ne 0 ]; then
  echo "[chain] GATE FAILED — 触发回退: DELETE origin='panel'（整图行不动）"
  "$PY" -u - <<'EOF'
import sqlite3
c = sqlite3.connect("zotero-figures.sqlite", timeout=30)
ids = [r[0] for r in c.execute("SELECT id FROM figures WHERE origin='panel'")]
c.executemany("DELETE FROM fts_figures WHERE rowid=?", [(i,) for i in ids])
c.execute("DELETE FROM figures WHERE origin='panel'")
c.commit()
tot = c.execute("SELECT COUNT(*) FROM figures").fetchone()[0]
print(f"[chain] 回退删除面板行={len(ids)} 剩余总行={tot}")
EOF
  echo "PANEL_ROLLED_BACK" > batch_tmp/PANEL_GATE.json
else
  echo "PANEL_GATE_OK" > batch_tmp/PANEL_GATE.json
fi

# 5. 复活双服务（清手动标记 + watchdog 拉起）
rm -f .manual_stop
"$PY" -u watchdog.py
sleep 10
curl -s -m 5 http://127.0.0.1:5173/api/stats && echo "" && echo "[chain] gallery back"
curl -s -m 5 -X POST http://127.0.0.1:23122/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' >/dev/null && echo "[chain] mcp back"

echo "CHAIN_V21_DONE" > batch_tmp/FINAL_DONE.json
echo "[chain] $(date '+%F %T') ALL DONE"
