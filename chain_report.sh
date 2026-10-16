#!/bin/bash
cd /d/Zotero/fig_db
PY="/d/Users/chmzs/Documents/Pixi_env/.pixi/envs/geo/python.exe"
while ! grep -q "scan done" poison_scan.log 2>/dev/null; do sleep 20; done
"$PY" -u make_poison_report.py
touch poison_report.done
