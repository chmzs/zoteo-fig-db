#!/bin/bash
cd /d/Zotero/fig_db
PY="/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe"
while [ ! -f supfig_targets.json ]; do sleep 15; done
sleep 5
OPENBLAS_NUM_THREADS=1 "$PY" -u reindex_families.py "D:\Zotero\fig_db\supfig_targets.json" > reindex_supfig.log 2>&1
nohup env OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1 "$PY" -u poison_scan.py > poison_scan.log 2>&1 &
echo SUPFIG_DONE >> reindex_supfig.log
