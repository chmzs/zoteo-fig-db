# zoteo-fig-db 夜跑总结报告

- 完成时间：2026-10-16 06:59:20
- 图库总量：**12865 张图 / 2202 篇文献**
- 抽取版本分布：{'1.5': 6070, '1.6': 3210, '1.7': 3585}

## 各出版商家族
| 家族 | 文献 | 图 |
|---|---|---|
| elsevier | 494 | 3439 |
| other | 482 | 2712 |
| cn | 364 | 1918 |
| copernicus | 103 | 881 |
| wiley | 181 | 859 |
| nature | 182 | 793 |
| agu | 81 | 536 |
| springer | 76 | 477 |
| mdpi | 57 | 419 |
| frontiers | 34 | 243 |
| aaas | 61 | 228 |
| pnas | 46 | 165 |
| cambridge | 14 | 64 |
| iop | 13 | 60 |
| tandf | 8 | 46 |
| gsw | 3 | 10 |
| oup | 2 | 10 |
| acs | 1 | 5 |

## 隔离清单（聚类）
- 4x  RuntimeError: code=5: too many nested graphics states

## 修复记录
- 假题注防御：题注上方无图形证据→拒绝（Elsevier 正文并入题注块问题）
- get_drawings / get_text(dict) 异常降级：MuPDF nested-graphics 不再整篇阵亡
- onnxruntime 线程限 2 + WORKERS 3→4→6 (workers pooled)：吞吐 ~2x
- 位图元数据免解码（get_image_info）：提取提速
- 期刊简称链：字段合法性校验（首字母子序列/词前缀）+ 同刊共识，拦截元数据错配脏值
