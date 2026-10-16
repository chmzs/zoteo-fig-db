#!/bin/bash
# 收尾链：等扫描完成 -> SI 候选重提 -> AGU 补完 -> 撤标记重启画廊
cd /d/Zotero/fig_db
PY="/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe"
while [ ! -f si_targets.json ]; do sleep 15; done
sleep 5
OPENBLAS_NUM_THREADS=1 "$PY" -u reindex_families.py "D:\\Zotero\\fig_db\\si_targets.json" > reindex_targets.log 2>&1
OPENBLAS_NUM_THREADS=1 "$PY" -u reindex_families.py agu_wiley >> reindex_targets.log 2>&1
rm -f .manual_stop
NO_BROWSER=1 nohup "/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/zoteo-fig-db.exe" server.py > server.log 2>&1 &
echo CHAIN_DONE >> reindex_targets.log
