#!/bin/bash
cd /d/Zotero/fig_db
PY="/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe"
while ! grep -q REINDEX_FAMILIES_DONE reindex_final.log 2>/dev/null; do sleep 20; done
OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1 "$PY" -u poison_scan.py > poison_scan.log 2>&1
echo POISON_FINAL >> poison_scan.log
