"""
zoteo-fig-db server (gallery + API)
Zero-dependency HTTP server based on Python's built-in http.server.
Fully compatible with Python 3.10 - 3.15+.
"""

import email.utils
import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from engine import IMAGE_DIR, FigureDB, FigureSearcher
import presets
import ratings

# 单例懒加载锁：ThreadingHTTPServer 下首屏并发请求会各建一个 FigureSearcher，
# 双份 e5 模型常驻内存（2026-11-15 审计）
_searcher_lock = threading.Lock()


def get_searcher():
    global searcher
    if searcher is None:
        with _searcher_lock:
            if searcher is None:
                searcher = FigureSearcher()
    return searcher


# ---- 后台索引任务（首次全库 / 增量更新）：进度必须来自真实计数 ----
_jobs = {}
_jobs_lock = threading.Lock()
JOB_STATE_PATH = os.path.join(BASE_DIR, "cache", "job_state.json")


def job_snapshot(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def job_latest():
    with _jobs_lock:
        if not _jobs:
            return None
        return dict(max(_jobs.values(), key=lambda item: item.get("started_at", 0)))


def _job_update(job_id, **fields):
    with _jobs_lock:
        job = _jobs.setdefault(job_id, {"id": job_id})
        job.update(fields)
        job["updated_at"] = time.time()
        snapshot = dict(job)
    try:
        with open(JOB_STATE_PATH, "w", encoding="utf-8") as state_file:
            json.dump(snapshot, state_file, ensure_ascii=False)
    except OSError:
        pass
    return snapshot


def _run_index_job(job_id, limit, force):
    from indexer import get_zotero_items_with_pdfs, index_papers

    try:
        _job_update(job_id, stage="scanning", message="扫描 Zotero 库")
        papers = get_zotero_items_with_pdfs(limit=limit)
        total = len(papers)
        before = db.get_stats()
        _job_update(job_id, stage="extracting", total=total, done=0,
                    message=f"准备抽取 {total} 篇")

        def on_progress(done, total_count, paper):
            _job_update(job_id, done=done, total=total_count,
                        current=(paper.get("title") or paper.get("item_key") or "")[:70],
                        current_journal=(paper.get("journal") or "")[:40])

        index_papers(papers, force_reindex=force, on_progress=on_progress)
        after = db.get_stats()
        gained = after["total_figures"] - before["total_figures"]
        _job_update(job_id, stage="done", done=total, total=total,
                    message=f"完成：图表 {before['total_figures']} → {after['total_figures']}（+{gained}）",
                    new_figures=gained, finished_at=time.time())
    except Exception as exc:
        _job_update(job_id, stage="error", message=f"{type(exc).__name__}: {exc}",
                    finished_at=time.time())


PORT = int(os.environ.get("GEO_FIGURE_PORT", 5173))
searcher = None
db = FigureDB()

STATIC_DIR = os.path.join(BASE_DIR, "static")



class ZoteoFigHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        """HEAD 与 GET 同路由：首页回 HTML 头、图片走同一个 ETag 判定，其余 404。"""
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        elif path.startswith("/static/"):
            self._serve_static(os.path.basename(path[len("/static/"):]), send_body=False)
        elif path.startswith(("/image/", "/thumb/")):
            self._serve_image(path, send_body=False)
        else:
            self.send_response(404)
            self.end_headers()

    STATIC_MIME = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
    }

    def _serve_static(self, name, send_body=True):
        """static/ 下的前端文件。

        一律 no-cache：改完 JS 后浏览器还在跑旧代码的坑踩过两次（2026-11-15），
        本地服务多传 40KB 换"刷新即生效"，比省带宽值。
        """
        static_path = os.path.join(STATIC_DIR, name)
        if not name or not os.path.isfile(static_path):
            self.send_response(404)
            self.end_headers()
            return
        mime = self.STATIC_MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
        with open(static_path, "rb") as static_file:
            body = static_file.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _serve_image(self, path, send_body=True):
        """图片/缩略图：ETag + Last-Modified + 304。

        图片一次入库即不再改写（重抽会覆盖同名文件 → mtime 变），
        故 (size, mtime_ns) 足以做版本标识，不必对整文件算哈希。
        一屏 24 张、滚到 500 张，跨设备走 overlay 时省掉全量重传。
        """
        prefix = "/thumb/" if path.startswith("/thumb/") else "/image/"
        fname = os.path.basename(urllib.parse.unquote(path[len(prefix):]))
        if prefix == "/thumb/" and not fname.endswith(".thumb.webp"):
            self.send_response(404)
            self.end_headers()
            return
        img_path = os.path.join(IMAGE_DIR, fname)
        # 空 fname 会落到 IMAGE_DIR 本身：必须挡掉，否则 stat 目录成功 → 200 + 目录大小头
        # + open(dir) 抛 IsADirectoryError → 响应已发头又被 500 覆写（2026-11-15 实测）
        if not fname or not os.path.isfile(img_path):
            self.send_response(404)
            self.end_headers()
            return
        try:
            file_stat = os.stat(img_path)
        except OSError:
            self.send_response(404)
            self.end_headers()
            return

        etag = f'"{file_stat.st_size:x}-{file_stat.st_mtime_ns:x}"'
        # formatdate(usegmt=True) 与 locale 无关，strftime("%a") 在中文 Windows 下会输出本地星期名
        last_modified = email.utils.formatdate(file_stat.st_mtime, usegmt=True)
        if self._not_modified(etag, file_stat.st_mtime):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return

        ext = os.path.splitext(fname)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/webp")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file_stat.st_size))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified)
        self.end_headers()
        if not send_body:
            return
        with open(img_path, "rb") as image_file:
            self.wfile.write(image_file.read())

    def _not_modified(self, etag, mtime):
        """If-None-Match 优先；无该头时退回 If-Modified-Since（HTTP 日期只到秒）。"""
        if_none_match = self.headers.get("If-None-Match")
        if if_none_match:
            if if_none_match.strip() == "*":
                return True
            return etag in [tag.strip() for tag in if_none_match.split(",")]
        if_modified_since = self.headers.get("If-Modified-Since")
        if not if_modified_since:
            return False
        try:
            since = email.utils.parsedate_to_datetime(if_modified_since).timestamp()
        except (TypeError, ValueError):
            return False
        return int(mtime) <= int(since)

    def do_GET(self):
        """全局兜底：未捕获异常一律回 500，绝不让请求线程静默断开（2026-10-28 审计发现）。"""
        try:
            self._do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._log_traceback("GET " + str(getattr(self, "path", "")))
            self._send_error_json(500, type(e).__name__, str(e))

    def _log_traceback(self, where):
        """完整栈落盘：只记 type+message 时 'NoneType is not iterable' 这类错误无处可查。"""
        try:
            with open(os.path.join(BASE_DIR, "cache", "server.log"), "a",
                      encoding="utf-8") as log_file:
                log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{where}]\n")
                log_file.write(traceback.format_exc())
        except OSError:
            pass

    ACCESS_LOG_ENABLED = os.environ.get("GEO_ACCESS_LOG", "1") != "0"

    def _send_json(self, code, payload):
        """统一的 JSON 响应：Content-Type/Length/end_headers 一处写死，避免新端点漏 header。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        """访问日志（cache/access.log，每请求一行）。

        原先 log_message 是 pass——正常请求零痕迹，排障只能靠用户截图
        （2026-11-15 服务空窗就是靠 curl 探端口才定位）。GEO_ACCESS_LOG=0 可关。
        """
        if not self.ACCESS_LOG_ENABLED:
            return
        try:
            with open(os.path.join(BASE_DIR, "cache", "access.log"), "a",
                      encoding="utf-8") as log_file:
                log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                               f"{self.command} {self.path} {code} {size} "
                               f"{self.client_address[0]}\n")
        except OSError:
            pass

    def _send_error_json(self, code, kind, message):
        # 服务端由 watchdog 以 DEVNULL 启动，stdout/stderr 全丢；异常必须自己落盘才能事后追溯
        try:
            with open(os.path.join(BASE_DIR, "cache", "server.log"), "a",
                      encoding="utf-8") as log_file:
                log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{code}] {kind}: {message}\n")
        except OSError:
            pass
        try:
            body = json.dumps({"error": kind, "message": (message or "")[:300]},
                              ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    @staticmethod
    def _int_param(query, name, default, lo=None, hi=None):
        """安全整数参数：非法值回落默认值并夹取到 [lo, hi]，不再让 int() 抛断连接。"""
        raw = (query.get(name, [None])[0] or "").strip()
        if raw == "":
            val = default
        else:
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = default
        # val 可能因 default=None 而保持 None，此时不参与夹取比较（None<int 会抛 TypeError）
        if val is not None:
            if lo is not None and val < lo:
                val = lo
            if hi is not None and val > hi:
                val = hi
        return val

    def _do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            # 只由 _serve_static 发一次响应：先 send_response/end_headers 会让第二个
            # 响应头被写进 body（浏览器把 "HTTP/1.0 200 OK" 当正文渲染，2026-11-15 实测）
            self._serve_static("index.html")
            return

        elif path.startswith("/static/"):
            self._serve_static(os.path.basename(path[len("/static/"):]))
            return

        elif path == "/api/stats":
            stats = db.get_stats()
            self._send_json(200, stats)
            return

        elif path == "/api/jobs/latest":
            snapshot = job_latest()
            self.send_response(200 if snapshot else 404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot or {"error": "no job"},
                                        ensure_ascii=False).encode("utf-8"))
            return

        elif path.startswith("/api/jobs/"):
            snapshot = job_snapshot(path[len("/api/jobs/"):])
            self.send_response(200 if snapshot else 404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot or {"error": "job not found"},
                                        ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/presets":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"presets": presets.load()},
                                        ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/urls":
            self._send_json(200, {"urls": reachable_urls()})
            return

        elif path == "/api/search":
            q = query.get("q", [""])[0]
            top_k = self._int_param(query, "top_k", 20, 1, 500)
            journal = query.get("journal", [None])[0]
            # 年份非法值直接丢弃（不再传字符串给引擎的 int() 抛异常）
            year_min = self._int_param(query, "year_min", None, 1800, 2200)
            year_max = self._int_param(query, "year_max", None, 1800, 2200)
            item_key = query.get("item_key", [None])[0]
            fig_no = query.get("fig_no", [None])[0]
            author = query.get("author", [None])[0]
            journal_exact = query.get("journal_exact", ["0"])[0] in ("1", "true", "yes")
            offset = self._int_param(query, "offset", 0, 0, 100000)
            # 画廊默认只出整图行（工单§二.2：默认视图不变）；panels=1 才透传面板行
            origin = None if query.get("panels", ["0"])[0] in ("1", "true", "yes") else "whole"
            # 个人评分过滤：只在明确传参时生效，未传 = 不按评分筛（默认视图不变）
            star_min = self._int_param(query, "star_min", None, 1, 5)

            results = get_searcher().search(
                query=q,
                top_k=top_k,
                journal_filter=journal,
                year_min=year_min,
                year_max=year_max,
                item_key=item_key,
                fig_no=fig_no,
                offset=offset,
                origin=origin,
                author=author,
                journal_exact=journal_exact,
                rating_min=star_min,
                rating_map=ratings.as_lookup(),  # 始终传：结果要带 rating 供前端渲染已点亮星
            )
            self._send_json(200, results)
            return

        elif path == "/api/facets":
            # 统计改由 FigureSearcher.facets() 提供：按缓存签名缓存，且不再读私有 _metas
            self._send_json(200, get_searcher().facets())
            return

        elif path.startswith("/image/") or path.startswith("/thumb/"):
            self._serve_image(path)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        """全局兜底：未捕获异常一律回 500（与 do_GET 同策略）。"""
        try:
            self._do_POST()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._log_traceback("POST " + str(getattr(self, "path", "")))
            self._send_error_json(500, type(e).__name__, str(e))

    def _do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/search":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                body = None
            if not isinstance(body, dict):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"json body required"}')
                return
            qs = body.get("q", body.get("queries", ""))
            single = isinstance(qs, str)
            qlist = [qs] if single else list(qs or [])
            qlist = [x.strip() for x in qlist if isinstance(x, str) and x.strip()][:50]
            if not qlist:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"q: string or list(<=50) required"}')
                return
            top_k = max(1, min(500, int(body.get("top_k", 20))))
            star_min = body.get("star_min")
            try:
                star_min = int(star_min) if star_min not in (None, "") else None
            except (TypeError, ValueError):
                star_min = None
            if star_min is not None:
                star_min = max(1, min(5, star_min))
            kw = dict(journal_filter=body.get("journal"), year_min=body.get("year_min"),
                      year_max=body.get("year_max"), item_key=body.get("item_key"),
                      fig_no=body.get("fig_no"), offset=int(body.get("offset", 0) or 0),
                      origin=None if str(body.get("panels", "0")).lower() in ("1", "true", "yes") else "whole",
                      author=body.get("author"),
                      journal_exact=str(body.get("journal_exact", "0")).lower() in ("1", "true", "yes"),
                      rating_min=star_min, rating_map=ratings.as_lookup())
            out = [get_searcher().search(x, top_k=top_k, **kw) for x in qlist]
            payload = out[0] if single else {"results": out}
            self._send_json(200, payload)
            return

        if path == "/api/presets":
            # 整体替换：前端持有全量列表，避免逐条增删在并发下叠加错乱
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except (TypeError, ValueError):
                body = None
            try:
                if not isinstance(body, dict):
                    raise ValueError("JSON body required")
                saved = presets.save(body.get("presets"))
            except (ValueError, TypeError) as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(exc)},
                                            ensure_ascii=False).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "presets": saved},
                                        ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/rate":
            # 个人评分写入：独立 sidecar（ratings.json），不碰 figures 表
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                body = None
            try:
                if not isinstance(body, dict):
                    raise ValueError("JSON body required")
                stars = ratings.set_rating(body.get("item_key"), body.get("fig_no"),
                                           body.get("stars"))
            except (ValueError, TypeError) as exc:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(exc)},
                                            ensure_ascii=False).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "stars": stars,
                                         "summary": ratings.summarize()},
                                        ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/jobs/index":
            # 首次索引与增量更新共用一个入口：空库自动全量，否则最近 30 篇
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except (TypeError, ValueError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            empty_library = db.get_stats().get("total_figures", 0) == 0
            limit = body.get("limit")
            if limit is None:
                limit = None if empty_library else 30
            force = bool(body.get("force", True))
            # 旧任务若还停在未完成状态（进程重启/线程异常），标成 error 免得前端一直轮询僵尸任务
            with _jobs_lock:
                for stale in _jobs.values():
                    if stale.get("stage") not in ("done", "error"):
                        stale["stage"] = "error"
                        stale["message"] = "被新的更新任务替代"
                        stale["finished_at"] = time.time()
            job_id = uuid.uuid4().hex[:12]
            _job_update(job_id, id=job_id, kind="index", stage="queued",
                        total=0, done=0, started_at=time.time(),
                        mode="全库" if limit is None else f"最近 {limit} 篇",
                        message="排队中")
            threading.Thread(target=_run_index_job, args=(job_id, limit, force),
                             daemon=True).start()
            self.send_response(202)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "accepted", "job_id": job_id},
                                        ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/update":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                body = {}
            keys = {str(k).upper() for k in (body.get("item_keys") or []) if k}
            try:
                from indexer import get_zotero_items_with_pdfs, index_papers
                if keys:
                    # 定向补录/重提：新篇建图；已入库(如刚拼接了附件 PDF)清场 redo（<=500/请求）
                    papers = [pp for pp in get_zotero_items_with_pdfs(limit=None)
                              if pp["item_key"].upper() in keys][:500]
                    for pp in papers:
                        db.remove_item(pp["item_key"])
                else:
                    # Scan recent 30 papers
                    papers = get_zotero_items_with_pdfs(limit=30)
                before_stats = db.get_stats()
                if papers:
                    index_papers(papers, force_reindex=True)
                after_stats = db.get_stats()
                new_figs = after_stats["total_figures"] - before_stats["total_figures"]
                
                self._send_json(200, {"status": "ok", "new_figures": new_figs})
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        elif path == "/api/shutdown":
            self._send_json(200, {"status": "ok", "message": "Server shutting down..."})
            # 写入手动停止标记：看门狗 5 分钟检查时将尊重该标记不再自动拉起
            try:
                open(os.path.join(BASE_DIR, ".manual_stop"), "w").close()
            except Exception:
                pass
            
            # Asynchronously shutdown the server and companion mcp server
            def killer():
                time.sleep(0.5)
                # 联动停掉 23122 MCP 读者进程。
                # 注意：中文 Windows 下 netstat 输出是 GBK，text=True 默认按 UTF-8 解码会
                # 抛 UnicodeDecodeError 并被静默吞掉 → MCP 永不退出（2026-10-28 审计实测）。
                try:
                    import subprocess

                    r = subprocess.run(["netstat", "-ano"], capture_output=True,
                                       encoding="utf-8", errors="replace")
                    for line in (r.stdout or "").splitlines():
                        if ":23122" in line and "LISTENING" in line:
                            pid = line.strip().split()[-1]
                            if pid.isdigit():
                                subprocess.run(["taskkill", "/PID", pid, "/F"],
                                               capture_output=True)
                except Exception:
                    pass
                os._exit(0)
            threading.Thread(target=killer).start()
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def reachable_urls():
    """稳定访问地址：本机回环 + overlay 恒定地址（100.64.0.0/10 段）。

    刻意不列出 WLAN 动态地址（192.168.*）：它随换网络/路由器重启漂移，
    且所有配置、快捷方式、MCP 端点均只依赖回环与 overlay（2026-10-28 收敛）。
    """
    urls = [f"http://127.0.0.1:{PORT}"]
    try:
        import ipaddress
        import socket

        overlay = ipaddress.ip_network("100.64.0.0/10")
        for ip in sorted(set(socket.gethostbyname_ex(socket.gethostname())[2])):
            if ip.startswith("127.") or ip == "0.0.0.0":
                continue
            try:
                if ipaddress.ip_address(ip) in overlay:
                    urls.append(f"http://{ip}:{PORT}")
            except ValueError:
                continue
    except Exception:
        pass
    return urls


class SingleInstanceHTTPServer(ThreadingHTTPServer):
    """禁用 SO_REUSEADDR 的画廊服务器。

    allow_reuse_address 是 TCPServer/HTTPServer 的类属性，设在 handler 上无效
    （2026-10-28 首次修就把属性放错了位置，实测仍能双绑）。
    Windows 下 SO_REUSEADDR 会让两个进程同时绑同一端口（连接随机分流、双缓存
    双行为，实测 5173 出现双监听）。关掉后重复启动直接抛 10048，
    由看门狗/启动脚本的端口判活决定是否拉起，绝不再产生第二个实例。
    """

    allow_reuse_address = False


def run():
    bind_host = os.environ.get("GEO_FIGURE_HOST", "0.0.0.0")
    server_address = (bind_host, PORT)
    httpd = SingleInstanceHTTPServer(server_address, ZoteoFigHandler)
    print(f"zoteo-fig-db running at http://{bind_host}:{PORT}")
    for u in reachable_urls():
        print(f"  reachable: {u}")

    # Auto-open browser when port is ready
    if os.environ.get("NO_BROWSER", "0") != "1":
        def open_browser():
            time.sleep(0.3)
            try:
                import webbrowser
                webbrowser.open(f"http://{bind_host}:{PORT}")
            except Exception:
                pass
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    # 后台预热：只构建服务端内存缓存（向量矩阵+笔记映射），不向浏览器发送任何图片
    def warm_caches():
        try:
            time.sleep(0.5)
            get_searcher()._ensure_cache()
            import notes_index
            notes_index.get_notes_map()
        except Exception:
            pass

    import threading
    threading.Thread(target=warm_caches, daemon=True).start()

    httpd.serve_forever()


if __name__ == "__main__":
    bind_host = os.environ.get("GEO_FIGURE_HOST", "0.0.0.0")
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        in_use = (s.connect_ex((bind_host, PORT)) == 0)

    if in_use:
        import webbrowser
        webbrowser.open(f"http://{bind_host}:{PORT}")
        sys.exit(0)

    run()