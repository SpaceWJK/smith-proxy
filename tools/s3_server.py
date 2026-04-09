"""Knowledge Integration System — Local Proxy Server

CORS 제약 우회를 위한 로컬 프록시.
s3_manager.html을 서빙하고 GDI API 호출을 프록시합니다.
/api/dashboard 엔드포인트로 시스템 상태 모니터링 데이터를 제공합니다.

사용법:
  python s3_server.py          # http://localhost:9090
  python s3_server.py --port 8080
"""
import http.server
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys
import re
import argparse
import mimetypes
import sqlite3
from datetime import datetime, timedelta
from io import BytesIO
import socket
import time
try:
    import boto3
    from botocore.config import Config as _BotoConfig
    _S3_CLIENT = boto3.client("s3", region_name="ap-northeast-2", config=_BotoConfig(
        connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}
    ))
    _S3_BUCKET = "game-doc-insight-resource"
    _S3_AVAILABLE = True
except ImportError:
    _S3_AVAILABLE = False

GDI_API = (
    "http://k8s-llmopsalbgroup-2f93202457-431440703"
    ".ap-northeast-1.elb.amazonaws.com/game-doc-insight-ui/api"
)
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Admin 인증 ──────────────────────────────────────────────────
ADMIN_PW = "qateam2025@"

# ── 하트비트: 연결된 클라이언트 추적 (Admin 서버 전용) ───────────
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
# Windows CMD 팝업 방지 — 모든 subprocess 호출에 creationflags=_NO_WINDOW 적용 필수
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
_connected_clients = {}       # {client_id: {user, ip, last_seen, status}}
_clients_lock = threading.Lock()
_disconnect_queue = set()     # 강제 종료 대상 client_id

# ── Dashboard 데이터 소스 경로 ─────────────────────────────────
_PROJECT_ROOT = os.path.normpath(os.path.join(STATIC_DIR, ".."))
_BOT_SRC = os.path.join(_PROJECT_ROOT, "Slack Bot")
_BOT_DATA = os.path.join(_BOT_SRC, "data")
_LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")
_CACHE_DB = os.path.normpath(
    os.path.join(_PROJECT_ROOT, "..", "QA Ops", "mcp-cache-layer", "cache", "mcp_cache.db")
)
_OPS_DB = os.path.join(_LOGS_DIR, "ops_metrics.db")
_health_cache = {}  # DB 락 시 폴백용 캐시 (모듈 레벨 — 요청 간 유지)

# ── 브라우저 세션 관리 (중앙 서버: 다중 사용자 추적) ─────────────
_file_count_cache = {"total": 0, "updated": None}
_SESSION_TIMEOUT_SEC = 90   # 이 이상 heartbeat 없으면 자동 오프라인
_session_timeout_started = False
_session_timeout_lock = threading.Lock()


def _start_session_timeout_thread():
    """90초 이상 heartbeat 없는 클라이언트 자동 제거 (60초 주기)."""
    global _session_timeout_started
    with _session_timeout_lock:
        if _session_timeout_started:
            return
        _session_timeout_started = True

    def _run():
        while True:
            time.sleep(60)
            now = datetime.now()
            with _clients_lock:
                for cid in list(_connected_clients.keys()):
                    try:
                        last = datetime.strptime(
                            _connected_clients[cid]["last_seen"],
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if (now - last).total_seconds() > _SESSION_TIMEOUT_SEC:
                            _connected_clients.pop(cid, None)
                    except Exception:
                        pass
    threading.Thread(target=_run, daemon=True, name="kis-session-timeout").start()

_start_session_timeout_thread()
_BRAIN_DB = os.path.normpath(
    os.path.join(_PROJECT_ROOT, "..", "Prompt Cultivation", "brain", "brain.db")
)

# ── Claude Monitoring 데이터 소스 ────────────────────────────
_CLAUDE_HOME = os.path.join(os.path.expanduser("~"), ".claude")
_SESSION_META_DIR = os.path.join(_CLAUDE_HOME, "usage-data", "session-meta")
_CLAUDE_CONFIG_PATH = os.path.join(STATIC_DIR, "claude_config.json")
_MCP_ENDPOINTS = {
    "wiki": "https://mcp.sginfra.net/confluence-wiki-mcp/mcp",
    "gdi": "https://mcp-dev.sginfra.net/game-doc-insight-mcp/mcp",
    "jira": "https://mcp.sginfra.net/confluence-jira-mcp/mcp",
}

# ── 로컬 서버 헬스체크 대상 ─────────────────────────────────
_LOCAL_SERVERS = {
    "KIS Dashboard": {"url": "http://localhost:9090", "desc": "KIS 대시보드 서버"},
    "KIS Dashboard(Alt)": {"url": "http://localhost:9091", "desc": "KIS 대시보드 서버(Alt)"},
    "Vite Dev": {"url": "http://localhost:5174", "desc": "프론트엔드 Dev 서버", "optional": True},
    "Preview MCP": {"url": "http://localhost:9100", "desc": "Preview MCP 서버"},
    "Preview(LAN)": {"url": "http://10.5.31.110:9100", "desc": "Preview MCP (내부망)", "optional": True},
}

# ── 프로세스 설명 자동 매핑 ──────────────────────────────────
_PROCESS_DESC = {
    "slack_bot": "Slack QA Bot",
    "s3_server": "KIS 대시보드 서버",
    "auto_sync": "MCP 캐시 동기화",
    "claude_code": "Claude Code CLI",
    "other": "Python 프로세스",
}


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server + GDI API reverse proxy."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    # ── API proxy ───────────────────────────────────────────
    def do_GET(self):
        if self.path == "/api/dashboard":
            self._handle_dashboard()
        elif self.path == "/api/ops-metrics":
            self._handle_ops_metrics()
        elif self.path == "/api/admin/clients":
            self._handle_admin_clients()
        elif self.path == "/api/brain-metrics":
            self._handle_brain_metrics()
        elif self.path == "/api/claude-metrics":
            self._handle_claude_metrics()
        elif self.path == "/s3_admin.html":
            self._serve_admin_page()
        elif self.path.split("?")[0] in ("/", "/s3_manager.html"):
            self._serve_manager_page()
        elif self.path == "/api/count":
            self._handle_count()
        elif self.path.startswith("/api/s3-list"):
            self._handle_s3_list()
        elif self.path.startswith("/api/"):
            self._proxy_get()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/process/kill":
            self._handle_process_kill()
        elif self.path == "/api/process/cleanup":
            self._handle_process_cleanup()
        elif self.path == "/api/process/restart-bot":
            self._handle_process_restart_bot()
        elif self.path == "/api/server/restart":
            self._handle_server_restart()
        elif self.path == "/api/server/shutdown":
            self._handle_server_shutdown()
        elif self.path == "/api/heartbeat":
            self._handle_browser_heartbeat()
        elif self.path == "/api/heartbeat/leave":
            self._handle_browser_leave()
        elif self.path == "/api/admin/heartbeat":
            self._handle_admin_heartbeat()
        elif self.path == "/api/admin/disconnect":
            self._handle_admin_disconnect()
        elif self.path == "/api/delete":
            self._handle_s3_delete()
        elif self.path.startswith("/api/"):
            self._proxy_post()
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ── User page ──────────────────────────────────────────────
    def _serve_manager_page(self):
        """s3_manager.html 서빙. 브라우저 캐시 무효화로 항상 최신 버전 표시."""
        try:
            html_path = os.path.join(STATIC_DIR, "s3_manager.html")
            with open(html_path, "r", encoding="utf-8") as f:
                data = f.read().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._error_json(500, f"Manager page load failed: {e}")

    # ── S3 파일 수 조회 (GDI API 우회, boto3 직접) ──────────────
    def _handle_count(self):
        """GET /api/count — S3 파일 수를 boto3로 직접 조회. 5분간 캐시."""
        global _file_count_cache
        if not _S3_AVAILABLE:
            self._error_json(500, "boto3 not installed")
            return
        try:
            # 캐시 히트 (5분 이내)
            if _file_count_cache["updated"]:
                age = (datetime.now() - _file_count_cache["updated"]).total_seconds()
                if age < 300:
                    self._json_response({"success": True, "total_files": _file_count_cache["total"]})
                    return

            # S3 직접 카운트 (페이지네이션)
            total = 0
            kwargs = {"Bucket": _S3_BUCKET}
            while True:
                resp = _S3_CLIENT.list_objects_v2(**kwargs)
                total += resp.get("KeyCount", 0)
                if resp.get("IsTruncated"):
                    kwargs["ContinuationToken"] = resp["NextContinuationToken"]
                else:
                    break
            _file_count_cache = {"total": total, "updated": datetime.now()}
            self._json_response({"success": True, "total_files": total})
        except Exception as e:
            self._error_json(500, f"S3 connection failed: {e}")

    # ── Admin page ─────────────────────────────────────────────
    def _serve_admin_page(self):
        """s3_admin.html 물리 파일 서빙. 없으면 s3_manager.html에 config 주입."""
        try:
            # 1차: 물리 파일 s3_admin.html 존재 시 직접 서빙
            admin_path = os.path.join(STATIC_DIR, "s3_admin.html")
            if os.path.exists(admin_path):
                with open(admin_path, "r", encoding="utf-8") as f:
                    html = f.read()
            else:
                # 2차: s3_manager.html에 config injection (폴백)
                html_path = os.path.join(STATIC_DIR, "s3_manager.html")
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
                config_script = (
                    '<script>'
                    'window.KIS_MODE="admin";'
                    'window.KIS_ADMIN_PW="' + ADMIN_PW + '";'
                    '</script>'
                )
                html = html.replace("<head>", f"<head>\n{config_script}", 1)

            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._error_json(500, f"Admin page load failed: {e}")

    # ── Proxy internals ─────────────────────────────────────
    def _proxy_get(self):
        api_path = self.path[len("/api"):]  # strip /api prefix
        url = GDI_API + api_path
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", len(data))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._error_json(502, str(e))

    def _proxy_post(self):
        api_path = self.path[len("/api"):]
        url = GDI_API + api_path
        content_length = int(self.headers.get("Content-Length", 0))
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(content_length) if content_length else b""

        try:
            req = urllib.request.Request(url, data=body, method="POST")
            if content_type:
                req.add_header("Content-Type", content_type)
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_type = resp.headers.get("Content-Type", "application/json")
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp_type)
                self.send_header("Content-Length", len(data))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._error_json(502, str(e))

    # ── S3 직접 목록 조회 (GDI 캐시 우회) ──────────────────────
    def _handle_s3_list(self):
        """GET /api/s3-list?path=...&next_token=... — S3에서 직접 파일 목록 조회.

        2단계 조회:
        1) 첫 요청(next_token 없음): Delimiter='/' 로 폴더 목록 완전 수집
        2) 모든 요청: Delimiter 없이 파일 조회 (실제 S3 키 반환, '//' 누락 방지)
        """
        if not _S3_AVAILABLE:
            self._error_json(500, "boto3 not installed")
            return

        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        path = params.get("path", [""])[0]
        next_token = params.get("next_token", [None])[0]
        page_size = int(params.get("page_size", ["200"])[0])

        prefix = path if path.endswith("/") else path + "/"
        if prefix == "/":
            prefix = ""

        try:
            # ── 1단계: 폴더 목록 (첫 요청에서만, Delimiter 사용) ──
            folder_list = []
            if not next_token:
                folder_names = set()
                dk = {"Bucket": _S3_BUCKET, "Prefix": prefix, "Delimiter": "/"}
                while True:
                    dr = _S3_CLIENT.list_objects_v2(**dk)
                    for cp in dr.get("CommonPrefixes", []):
                        raw_name = cp["Prefix"][len(prefix):].rstrip("/")
                        # '//' 서브폴더 → name이 빈 문자열 → 스킵 (파일은 아래에서 처리)
                        clean_name = raw_name.lstrip("/")
                        if clean_name:
                            folder_names.add(clean_name)
                    if dr.get("IsTruncated"):
                        dk["ContinuationToken"] = dr["NextContinuationToken"]
                    else:
                        break
                folder_list = sorted([{
                    "name": n, "type": "folder",
                    "path": prefix + n + "/",
                } for n in folder_names], key=lambda x: x["name"])

            # ── 2단계: 파일 목록 (Delimiter 없이 — '//' 포함 실제 S3 키 반환) ──
            kwargs = {
                "Bucket": _S3_BUCKET,
                "Prefix": prefix,
                "MaxKeys": page_size,
                # Delimiter 없음: '//' 파일 누락 방지
            }
            if next_token:
                kwargs["ContinuationToken"] = next_token

            resp = _S3_CLIENT.list_objects_v2(**kwargs)

            files = []
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if key == prefix:
                    continue

                relative = key[len(prefix):]
                clean = relative.lstrip("/")

                # 하위 폴더 파일은 스킵 (폴더 목록에서 이미 표시)
                if "/" in clean:
                    continue

                files.append({
                    "name": clean,
                    "type": "file",
                    "key": key,
                    "path": key,
                    "size": obj.get("Size", 0),
                    "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                })

            # 파일명 기준 중복 제거
            seen = set()
            deduped = []
            for f in files:
                if f["name"] not in seen:
                    seen.add(f["name"])
                    deduped.append(f)

            result = {
                "success": True,
                "folders": folder_list,
                "files": deduped,
                "current_path": path,
                "next_token": resp.get("NextContinuationToken"),
                "has_more": resp.get("IsTruncated", False),
                "source": "s3-direct",
            }
            self._json_response(result)
        except Exception as e:
            self._error_json(500, f"S3 list failed: {e}")

    # ── S3 직접 삭제 (GDI UI API delete가 동작하지 않아 boto3로 직접 삭제) ──
    def _handle_s3_delete(self):
        """POST /api/delete — boto3로 S3 객체 직접 삭제.

        Quiet=False 사용: 실제 삭제된 키 목록을 S3가 반환하므로 정확한 카운트 가능.
        '//' 변형 확장: GDI API가 '//'를 '/'로 정규화하는 버그 대응.
        """
        if not _S3_AVAILABLE:
            self._error_json(500, "boto3 not installed — S3 direct delete unavailable")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""
        try:
            data = json.loads(body)
        except Exception:
            self._error_json(400, "Invalid JSON")
            return

        keys = data.get("keys", [])
        if not keys:
            self._json_response({"success": False, "error": "삭제할 파일이 선택되지 않았습니다."})
            return

        original_count = len(keys)

        # GDI API '//' → '/' 정규화 버그 대응: 원본 + '//' 변형 모두 삭제
        expanded = set()
        for k in keys:
            expanded.add(k)
            idx = k.rfind("/")
            if idx > 0:
                variant = k[:idx] + "/" + k[idx:]  # 'a/file' → 'a//file'
                expanded.add(variant)
        all_keys = list(expanded)

        # S3 delete_objects (Quiet=False → 실제 삭제된 키 반환)
        actually_deleted = set()
        total_errors = 0
        error_details = []
        BATCH = 1000
        for i in range(0, len(all_keys), BATCH):
            batch = all_keys[i:i + BATCH]
            try:
                resp = _S3_CLIENT.delete_objects(
                    Bucket=_S3_BUCKET,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": False}
                )
                # Quiet=False: Deleted 배열에 실제 삭제된 키 반환
                for d in resp.get("Deleted", []):
                    actually_deleted.add(d["Key"])
                for e in resp.get("Errors", []):
                    total_errors += 1
                    error_details.append({"key": e.get("Key"), "error": e.get("Message")})
            except Exception as e:
                total_errors += len(batch)
                error_details.append({"key": batch[0] if batch else "?", "error": str(e)})

        # 원본 키 기준으로 실제 삭제된 수 계산 (// 변형은 제외)
        real_deleted = 0
        for k in keys:
            idx = k.rfind("/")
            variant = k[:idx] + "/" + k[idx:] if idx > 0 else None
            if k in actually_deleted or (variant and variant in actually_deleted):
                real_deleted += 1

        result = {
            "success": total_errors == 0 and real_deleted == original_count,
            "deleted": real_deleted,
            "requested": original_count,
            "errors": total_errors,
            "message": f"{real_deleted}/{original_count}개 삭제" + (f", {total_errors}개 에러" if total_errors else ""),
        }
        if error_details:
            result["error_details"] = error_details[:10]

        self._json_response(result)

    # ── Dashboard API (로컬 데이터 수집, 프록시 아님) ─────────
    def _handle_dashboard(self):
        """6개 섹션 데이터를 수집하여 JSON 응답 반환."""
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "health": self._dash_health(),
            "cache": self._dash_cache(),
            "queries": self._dash_queries(),
            "scheduler": self._dash_scheduler(),
            "claims": self._dash_claims(),
            "activity": self._dash_activity(),
            "processes": self._dash_processes(),
            "token_usage": self._dash_token_usage(),
        }
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ── Dashboard: Section 1 — System Health ──────────────
    def _dash_health(self):
        try:
            # 봇 프로세스 확인 — PowerShell Get-CimInstance (wmic deprecated)
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter"
                 " \"name='python.exe' or name='pythonw.exe'\" |"
                 " Select-Object -ExpandProperty CommandLine"],
                text=True, timeout=10, creationflags=_NO_WINDOW,
            )
            bot_running = "slack_bot" in out.lower()
        except Exception:
            bot_running = False

        # 소스별 최근 sync 기록 — 동적 스캔 + 메타데이터 라벨링
        # 새 동기화 소스 등록 시 _SYNC_META에만 라벨 추가하면 끝
        # sync_log에 source_type이 추가되면 자동 표시 (메타 미정의는 source_type 그대로 라벨로 사용)
        global _health_cache
        sync_by_source = {}
        last_sync = None
        try:
            conn = sqlite3.connect(f"file:{_CACHE_DB}?mode=ro", uri=True, timeout=30)
            cur = conn.cursor()
            # 1) DB에서 모든 source_type 동적 조회
            cur.execute("SELECT DISTINCT source_type FROM sync_log")
            db_sources = [r[0] for r in cur.fetchall() if r[0]]
            # 2) 메타에 있지만 DB에 없는 소스도 포함 (초기 상태 표시용)
            all_sources = set(db_sources) | set(self._SYNC_META.keys())

            # 3) 소스별 최신 1건씩 조회
            for src in sorted(all_sources):
                cur.execute(
                    "SELECT source_type, started_at, finished_at, status, "
                    "pages_scanned, pages_updated, duration_sec, error_message "
                    "FROM sync_log WHERE source_type = ? "
                    "ORDER BY started_at DESC LIMIT 1",
                    (src,),
                )
                row = cur.fetchone()
                meta = self._SYNC_META.get(src, {
                    "label": src.replace("_", " ").title(),
                    "category": "기타",
                    "color": "#7a9ab8",
                })
                if row:
                    sync_by_source[src] = {
                        "source": row[0], "started_at": row[1],
                        "finished_at": row[2], "status": row[3],
                        "scanned": row[4], "updated": row[5],
                        "duration": row[6], "error": row[7],
                        "label": meta["label"],
                        "category": meta["category"],
                        "color": meta["color"],
                    }
                else:
                    # 초기 상태: sync_log 비어있음
                    sync_by_source[src] = {
                        "source": src, "started_at": None,
                        "finished_at": None, "status": "unknown",
                        "scanned": 0, "updated": 0,
                        "duration": None, "error": None,
                        "label": meta["label"],
                        "category": meta["category"],
                        "color": meta["color"],
                    }
            # GDI enrichment은 N/A (원본 파일 기반이므로 enrichment 불필요)
            if "gdi" in sync_by_source:
                sync_by_source["gdi"]["enrichment_applicable"] = False

            # 전체 최근 1건 (하위호환)
            cur.execute(
                "SELECT source_type, started_at, status, duration_sec "
                "FROM sync_log ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                last_sync = {
                    "source": row[0], "time": row[1],
                    "status": row[2], "duration": row[3],
                }
            conn.close()
            # DB 정상 조회 시 모듈 레벨 캐시 갱신
            _health_cache = {"sync_by_source": sync_by_source, "last_sync": last_sync}
        except Exception:
            # DB 락 등 실패 시 캐시 폴백
            sync_by_source = _health_cache.get("sync_by_source", {})
            last_sync = _health_cache.get("last_sync")

        # Task Scheduler 상태 — 동적 스캔 (MCP/Slack/Brain/KIS 키워드 자동 매칭)
        # 새 태스크 등록 시 코드 수정 불필요 — 키워드만 맞으면 자동 표시
        task_scheduler = {}
        _TASK_KEYWORDS = ("MCP", "mcp", "Slack", "slack", "Brain", "brain", "KIS", "kis", "QA", "qa")
        try:
            # 1) CSV로 전체 태스크 + NextRun 조회
            csv_out = subprocess.check_output(
                ['schtasks', '/query', '/fo', 'CSV', '/nh'],
                text=True, timeout=10, creationflags=_NO_WINDOW,
                encoding='utf-8', errors='replace',
            )
            seen_tasks = set()
            matched_tasks = []  # [(full_path, display_name, next_run)]
            for line in csv_out.strip().splitlines():
                parts = line.split(',')
                if not parts:
                    continue
                full_name = parts[0].strip().strip('"')
                # 표시명: 마지막 \ 이후
                display = full_name.rsplit('\\', 1)[-1] if '\\' in full_name else full_name.lstrip('\\')
                if not display or display in seen_tasks:
                    continue
                if any(kw in display for kw in _TASK_KEYWORDS):
                    next_run = parts[1].strip().strip('"') if len(parts) > 1 else "N/A"
                    matched_tasks.append((full_name, display, next_run))
                    seen_tasks.add(display)

            # 2) 매칭된 태스크별 Enabled 확인 (XML 1회씩)
            for full_name, display, next_run in matched_tasks:
                try:
                    xml_out = subprocess.check_output(
                        ['schtasks', '/query', '/tn', full_name.lstrip('\\'), '/xml'],
                        text=True, timeout=5, creationflags=_NO_WINDOW,
                        encoding='utf-16', errors='replace',
                    )
                    enabled_match = re.search(r'<Enabled>(true|false)</Enabled>', xml_out, re.IGNORECASE)
                    enabled = enabled_match.group(1).lower() == 'true' if enabled_match else True
                except Exception:
                    enabled = True
                # 메타 라벨 매칭 — 키워드 첫 매칭 적용, 없으면 schtasks 이름 그대로
                label = display
                category = "기타"
                color = "#7a9ab8"
                for key, lbl, cat, clr in self._TASK_META:
                    if key in display:
                        label, category, color = lbl, cat, clr
                        break
                task_scheduler[display] = {
                    "enabled": enabled,
                    "next_run": next_run,
                    "label": label,
                    "category": category,
                    "color": color,
                }
        except Exception:
            pass

        # 스케줄러 활성 여부 (config.json 스케줄 수)
        sched_count = 0
        try:
            with open(os.path.join(_BOT_SRC, "config.json"), "r", encoding="utf-8") as f:
                cfg = json.load(f)
            schedules = cfg.get("schedules", [])
            sched_count = len([s for s in schedules if s.get("type") != "mission"])
        except Exception:
            pass

        return {
            "bot_process": bot_running,
            "scheduler_count": sched_count,
            "last_sync": last_sync,
            "sync_by_source": sync_by_source,
            "task_scheduler": task_scheduler,
        }

    # ── Dashboard: Section 2 — Cache Status ───────────────
    def _dash_cache(self):
        try:
            conn = sqlite3.connect(f"file:{_CACHE_DB}?mode=ro", uri=True, timeout=3)
            cur = conn.cursor()

            # 소스별 노드 수
            cur.execute("SELECT source_type, COUNT(*) FROM nodes GROUP BY source_type")
            by_source = {}
            total = 0
            for row in cur.fetchall():
                by_source[row[0]] = {"count": row[1]}
                total += row[1]

            # 소스별 freshness (7일 이내 비율)
            cur.execute("""
                SELECT n.source_type,
                    COUNT(*) as total,
                    SUM(CASE WHEN dm.cached_at >= datetime('now', '-7 days') THEN 1 ELSE 0 END) as fresh
                FROM nodes n JOIN doc_meta dm ON n.id = dm.node_id
                GROUP BY n.source_type
            """)
            for row in cur.fetchall():
                src = row[0]
                if src in by_source:
                    by_source[src]["freshness"] = round(row[2] / row[1] * 100) if row[1] else 0

            # 최근 sync 히스토리 (최근 10건)
            cur.execute(
                "SELECT source_type, started_at, status, pages_updated, duration_sec "
                "FROM sync_log ORDER BY started_at DESC LIMIT 10"
            )
            sync_history = []
            for row in cur.fetchall():
                sync_history.append({
                    "source": row[0], "time": row[1], "status": row[2],
                    "pages_updated": row[3], "duration": row[4],
                })

            # 소스별 body 적재율 (doc_content JOIN)
            cur.execute("""
                SELECT n.source_type,
                    COUNT(*) as total,
                    SUM(CASE WHEN dc.id IS NOT NULL THEN 1 ELSE 0 END) as with_body,
                    SUM(CASE WHEN dc.body_text IS NOT NULL AND dc.body_text != '' THEN 1 ELSE 0 END) as has_text
                FROM nodes n
                LEFT JOIN doc_content dc ON dc.node_id = n.id
                GROUP BY n.source_type
            """)
            for row in cur.fetchall():
                src = row[0]
                if src in by_source:
                    by_source[src]["body_loaded"] = row[2]
                    by_source[src]["body_has_text"] = row[3]
                    by_source[src]["body_rate"] = round(row[2] / row[1] * 100) if row[1] else 0

            # DB 파일 크기
            db_size_mb = round(os.path.getsize(_CACHE_DB) / (1024 * 1024), 1)

            conn.close()
            return {
                "total_nodes": total,
                "by_source": by_source,
                "db_size_mb": db_size_mb,
                "sync_history": sync_history,
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Dashboard: Section 3 — Query Performance ──────────
    def _dash_queries(self):
        today = datetime.now().strftime("%Y-%m-%d")
        sources = {"wiki": "wiki_query.log", "gdi": "gdi_query.log", "jira": "jira_query.log"}
        by_source = {}
        recent = []
        total_count = 0
        total_dur = 0
        dur_count = 0

        for src, filename in sources.items():
            log_path = os.path.join(_LOGS_DIR, filename)
            lines = self._tail_file(log_path, 200)
            src_count = 0
            for line in lines:
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    continue
                ts = parts[0]
                if not ts.startswith(today):
                    continue
                src_count += 1
                status = parts[1] if len(parts) > 1 else "?"
                # duration 파싱 (마지막 필드, 예: "7701ms")
                dur_ms = 0
                if len(parts) >= 3:
                    dur_match = re.search(r"(\d+)ms$", parts[-1])
                    if dur_match:
                        dur_ms = int(dur_match.group(1))
                        total_dur += dur_ms
                        dur_count += 1
                # user 파싱
                user = ""
                for p in parts:
                    um = re.search(r"user=(\w+)", p)
                    if um:
                        user = um.group(1)
                        break
                recent.append({
                    "time": ts[11:16] if len(ts) >= 16 else ts,
                    "source": src, "status": status, "user": user,
                    "duration_ms": dur_ms,
                })
            by_source[src] = src_count
            total_count += src_count

        # answer_miss.log에서 캐시 히트율 계산
        cache_hit = 0
        cache_total = 0
        miss_path = os.path.join(_LOGS_DIR, "answer_miss.log")
        miss_lines = self._tail_file(miss_path, 200)
        for line in miss_lines:
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            ts = parts[0]
            if not ts.startswith(today):
                continue
            cache_total += 1
            if "CACHE_HIT" in parts[1]:
                cache_hit += 1

        # 최근 항목 시간 역순 정렬 후 상위 15개
        recent.sort(key=lambda x: x["time"], reverse=True)
        recent = recent[:15]

        avg_dur = round(total_dur / dur_count) if dur_count else 0
        hit_rate = round(cache_hit / cache_total, 2) if cache_total else 0

        return {
            "today_count": total_count,
            "by_source": by_source,
            "avg_duration_ms": avg_dur,
            "cache_hit_rate": hit_rate,
            "cache_total": cache_total,
            "recent": recent,
        }

    # ── Dashboard: Section 4 — Scheduler ──────────────────
    def _dash_scheduler(self):
        schedules = []
        missions = []
        channel_map = {}  # channel_id → channel_name (미션에서 추출)
        try:
            with open(os.path.join(_BOT_SRC, "config.json"), "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for s in cfg.get("schedules", []):
                stype = s.get("type", "")
                channel_id = s.get("channel", "")
                if stype == "mission":
                    # 미션에서 채널 이름 추출
                    m = s.get("mission", {})
                    if m.get("channel_name"):
                        channel_map[channel_id] = m["channel_name"]
                    continue
                # 비미션 스케줄은 모두 "알림" 카테고리
                category = "notification"
                schedules.append({
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "type": stype,
                    "category": category,
                    "trigger": s.get("time", s.get("weekday", "")),
                    "channel": channel_id,
                    "enabled": s.get("enabled", False),
                })
        except Exception:
            pass

        # sent_checklist_log에서 최근 실행 상태 매핑
        today = datetime.now().strftime("%Y-%m-%d")
        sent_log = {}
        try:
            with open(os.path.join(_BOT_DATA, "sent_checklist_log.json"), "r", encoding="utf-8") as f:
                sent_data = json.load(f)
            # 오늘 또는 최근 날짜 확인
            for date_key in sorted(sent_data.keys(), reverse=True):
                for entry in sent_data[date_key]:
                    sid = entry.get("schedule_id", "")
                    if sid and sid not in sent_log:
                        sent_log[sid] = {
                            "last_fire": date_key,
                            "status": entry.get("status", "sent"),
                        }
                if len(sent_log) >= len(schedules):
                    break
        except Exception:
            pass

        # 스케줄에 마지막 실행 상태 병합
        for s in schedules:
            log_entry = sent_log.get(s["id"], {})
            s["last_fire"] = log_entry.get("last_fire", "")
            s["status"] = log_entry.get("status", "")

        # mission_state.json + config의 mission 스케줄 병합
        try:
            with open(os.path.join(_BOT_SRC, "mission_state.json"), "r", encoding="utf-8") as f:
                ms = json.load(f)
            # config.json에서 mission 스케줄의 채널/이름 재조회
            mission_cfg = {}
            try:
                with open(os.path.join(_BOT_SRC, "config.json"), "r", encoding="utf-8") as f2:
                    cfg2 = json.load(f2)
                for s2 in cfg2.get("schedules", []):
                    if s2.get("type") == "mission":
                        m2 = s2.get("mission", {})
                        mission_cfg[s2["id"]] = {
                            "channel": s2.get("channel", ""),
                            "channel_name": m2.get("channel_name", ""),
                            "name": m2.get("name", s2.get("name", "")),
                        }
            except Exception:
                pass
            for mid, mdata in ms.items():
                mc = mission_cfg.get(mid, {})
                missions.append({
                    "id": mid,
                    "number": mdata.get("mission_number", ""),
                    "name": mc.get("name", ""),
                    "progress": mdata.get("progress", 0),
                    "channel": mc.get("channel", ""),
                    "channel_name": mc.get("channel_name", ""),
                })
        except Exception:
            pass

        # 채널 이름 매핑 — 모든 채널 ID에 이름 부여
        # 1) 비미션 스케줄의 채널 (동일 채널 사용)
        for s in schedules:
            ch = s.get("channel", "")
            if ch and ch not in channel_map:
                channel_map[ch] = "메인 업무"
        # 2) 미션 채널은 위에서 이미 추출됨

        return {
            "schedules": schedules,
            "missions": missions,
            "channel_map": channel_map,
        }

    # ── Dashboard: Section 5 — Claims ─────────────────────
    def _dash_claims(self):
        try:
            with open(os.path.join(_BOT_DATA, "claims.json"), "r", encoding="utf-8") as f:
                claims_data = json.load(f)
            items = []
            total = 0
            # 날짜 역순으로 최근 10건
            for date_key in sorted(claims_data.keys(), reverse=True):
                for claim in claims_data[date_key]:
                    total += 1
                    if len(items) < 10:
                        items.append({
                            "date": date_key,
                            "category": claim.get("category", ""),
                            "user": claim.get("user_name", ""),
                            "content": claim.get("content", "")[:100],
                        })
            return {"total": total, "items": items}
        except Exception:
            return {"total": 0, "items": []}

    # ── Dashboard: Section 6 — Activity Log ───────────────
    def _dash_activity(self):
        """전체 로그를 시간순 머지하여 최근 30건 반환."""
        events = []
        today = datetime.now().strftime("%Y-%m-%d")

        # 쿼리 로그 3종
        for src, fname in [("wiki", "wiki_query.log"), ("gdi", "gdi_query.log"), ("jira", "jira_query.log")]:
            lines = self._tail_file(os.path.join(_LOGS_DIR, fname), 50)
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                ts = parts[0]
                status = parts[1]
                dur_match = re.search(r"(\d+)ms$", parts[-1])
                dur = f"{int(dur_match.group(1))/1000:.1f}s" if dur_match else ""
                events.append({
                    "time": ts, "source": src, "event": "query",
                    "detail": f"{status} {dur}".strip(),
                })

        # claim.log
        lines = self._tail_file(os.path.join(_LOGS_DIR, "claim.log"), 20)
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            events.append({
                "time": parts[0], "source": "claim", "event": "submit",
                "detail": parts[3] if len(parts) > 3 else "",
            })

        # sync_log (DB)
        try:
            conn = sqlite3.connect(f"file:{_CACHE_DB}?mode=ro", uri=True, timeout=3)
            cur = conn.cursor()
            cur.execute(
                "SELECT source_type, started_at, status, pages_updated, duration_sec "
                "FROM sync_log ORDER BY started_at DESC LIMIT 10"
            )
            for row in cur.fetchall():
                events.append({
                    "time": row[1], "source": row[0], "event": "sync",
                    "detail": f"{row[2]} {row[3]}p {row[4]:.0f}s" if row[4] else row[2],
                })
            conn.close()
        except Exception:
            pass

        # 시간 역순 정렬, 상위 30건
        events.sort(key=lambda x: x.get("time", ""), reverse=True)
        return events[:30]

    # ── Dashboard: Section 7 — Process Monitor (VIEW ONLY) ──
    # 민감 정보 마스킹 패턴
    _SENSITIVE_RE = re.compile(
        r'(--?(?:token|key|password|secret|api.?key)\s*[=\s])\S+',
        re.IGNORECASE,
    )

    # ── 동기화 소스 메타데이터 (단일 진실 공급원) ──────────────────
    # 새 sync source 추가 시 여기 한 줄 추가, 미정의 source는 자동으로 source_type 그대로 표시
    _SYNC_META = {
        "wiki":       {"label": "Wiki Sync",        "category": "MCP 캐시", "color": "#5b8a72"},
        "jira":       {"label": "Jira Sync",        "category": "MCP 캐시", "color": "#7c5cbf"},
        "gdi":        {"label": "GDI Sync",         "category": "MCP 캐시", "color": "#b8863b"},
        "enrichment": {"label": "Enrichment",       "category": "MCP 캐시", "color": "#2a8a9e"},
        # ── QA 대시보드 (5174) — quest_scheduler.py가 INSERT ──
        "quest_weekly_backup":  {"label": "퀘스트 주간 백업",  "category": "QA 대시보드", "color": "#3b6ea5"},
        "quest_monthly_backup": {"label": "퀘스트 월간 백업",  "category": "QA 대시보드", "color": "#3b6ea5"},
        "quest_monthly_export": {"label": "퀘스트 월간 Export", "category": "QA 대시보드", "color": "#3b6ea5"},
        "quest_backup_cleanup": {"label": "백업 정리",          "category": "QA 대시보드", "color": "#3b6ea5"},
        "quest_wiki_export":    {"label": "퀘스트 Wiki Export", "category": "QA 대시보드", "color": "#3b6ea5"},
        "guild_daily":          {"label": "길드 일일 작업",     "category": "QA 대시보드", "color": "#3b6ea5"},
        "season_reset":         {"label": "시즌 리셋",          "category": "QA 대시보드", "color": "#3b6ea5"},
    }

    # ── Task Scheduler 메타데이터 (단일 진실 공급원) ──────────────
    # 키워드 매칭으로 라벨 부여. 미매칭은 schtasks 이름 그대로 표시
    # (key, label, category, color) 순서대로 첫 매칭 적용
    _TASK_META = [
        ("MCP-AutoSync-Delta",    "MCP 증분 동기화",   "MCP 캐시",   "#5b8a72"),
        ("MCP-AutoSync-FullWiki", "Wiki 전체 동기화",  "MCP 캐시",   "#5b8a72"),
        ("MCP_Process_Cleanup",   "프로세스 정리",     "유지보수",   "#9a8e7d"),
        ("SlackQABot",            "Slack QA Bot",      "Slack Bot",  "#5b8a72"),
        ("Quest_Weekly",          "퀘스트 주간 백업",  "QA 대시보드", "#3b6ea5"),
        ("Quest_Monthly",         "퀘스트 월간 백업",  "QA 대시보드", "#3b6ea5"),
        ("Quest_Export",          "Wiki Export",       "QA 대시보드", "#3b6ea5"),
        ("Guild_Daily",           "길드 일일 작업",    "QA 대시보드", "#3b6ea5"),
        ("Season_Reset",          "시즌 리셋",         "QA 대시보드", "#3b6ea5"),
    ]

    # ── 프로세스 타입 메타데이터 (단일 진실 공급원) ────────────────
    # 새 프로세스 타입 추가 시 여기 한 곳만 수정하면 백엔드/프론트 동시 반영
    _PROC_TYPE_META = {
        "slack_bot":    {"color": "#5b8a72", "visible": True},
        "s3_server":    {"color": "#7c5cbf", "visible": True},
        "auto_sync":    {"color": "#5b8a72", "visible": True},
        "enrichment":   {"color": "#b8863b", "visible": True},
        "init_brain":   {"color": "#c45c4a", "visible": True},
        "weekly_batch": {"color": "#2a8a9e", "visible": True},
        "vite_dev":     {"color": "#1e7e6f", "visible": True},
        "issue_backend": {"color": "#3b6ea5", "visible": True},
        "other_python": {"color": "#9a8e7d", "visible": False},  # 좀비/중복일 때만 표시
    }

    def _dash_processes(self):
        """관련 Python/Node 프로세스 목록 + 좀비/중복 판정 + 시스템 상태."""
        procs = []
        try:
            # ── Step 1: 리스닝 포트 → PID 매핑 (Vite 포트 식별용) ──
            port_map = {}
            try:
                port_ps = (
                    "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue "
                    "| Select-Object OwningProcess,LocalPort "
                    "| ConvertTo-Json -Compress"
                )
                port_out = subprocess.check_output(
                    ['powershell', '-NoProfile', '-Command', port_ps],
                    text=True, timeout=8, creationflags=_NO_WINDOW,
                ).strip()
                if port_out and port_out not in ("null", ""):
                    raw_list = json.loads(port_out)
                    if isinstance(raw_list, dict):
                        raw_list = [raw_list]
                    for entry in raw_list:
                        ep = entry.get("OwningProcess")
                        lp = entry.get("LocalPort")
                        if ep and lp:
                            pid_key = int(ep)
                            existing = port_map.get(pid_key, "")
                            port_map[pid_key] = (existing + "," + str(lp)).strip(",")
            except Exception:
                pass  # 포트 맵 실패해도 나머지 계속

            # ── Step 2: Python + Node 프로세스 일괄 조회 ──
            ps_cmd = (
                "Get-CimInstance Win32_Process "
                "-Filter \"name='python.exe' or name='pythonw.exe' or name='node.exe'\" "
                "| ForEach-Object { "
                "  $cpu = try { (Get-Process -Id $_.ProcessId -ErrorAction Stop).CPU } catch { 0 }; "
                "  [pscustomobject]@{ "
                "    ProcessId=$_.ProcessId; Name=$_.Name; "
                "    MemMB=[math]::Round($_.WorkingSetSize/1MB,1); "
                "    CPU=[math]::Round($cpu,1); "
                "    CommandLine=$_.CommandLine; "
                "    Created=$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss') "
                "  } "
                "} | ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                text=True, timeout=15, creationflags=_NO_WINDOW,
            ).strip()
            if not out:
                return self._empty_processes()

            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]

            # ── Vite 포트 → 라벨 매핑 ──
            _VITE_PORTS = {
                "5174": ("vite_dev", "QA 대시보드"),
                "5175": ("vite_dev", "에이전트 팀"),
                "5176": ("vite_dev", "QA Workflow"),
            }
            # 전체 정리에서 Vite/Node 화이트리스트 (절대 zombie/duplicate 판정 안 함)
            _NODE_WHITELIST_CMD = ("claude", ".claude", "mcp-remote", "pdf-filler", "context7")

            # 프로세스 분류
            seen_types = {}     # type -> [proc_dicts]
            my_pid = os.getpid()

            for p in data:
                cmd = (p.get("CommandLine") or "").lower()
                pname = (p.get("Name") or "").lower()
                pid = p.get("ProcessId", 0)
                mem_mb = p.get("MemMB", 0)
                cpu = p.get("CPU", 0)
                pid_ports = port_map.get(pid, "")

                # ── node.exe 분류 ──
                if "node" in pname:
                    # 화이트리스트: Claude/MCP 관련 → 목록에서 제외
                    if any(w in cmd for w in _NODE_WHITELIST_CMD):
                        continue
                    # Vite 서버: 리스닝 포트 기반 식별
                    vite_label = None
                    for port, (vtype, vlabel) in _VITE_PORTS.items():
                        if port in pid_ports:
                            vite_label = vlabel
                            ptype, label = vtype, vlabel
                            break
                    if vite_label is None:
                        # 포트 미매핑 node: 알 수 없는 node → 목록 제외
                        continue
                else:
                    # ── python.exe / pythonw.exe 분류 ──
                    if "slack_bot" in cmd:
                        ptype, label = "slack_bot", "Slack Bot"
                    elif "s3_server" in cmd:
                        ptype, label = "s3_server", "KIS Server"
                    elif "issue dashboard" in cmd and "server.py" in cmd:
                        ptype, label = "issue_backend", "Issue Dashboard API"
                    elif "auto_sync" in cmd:
                        ptype, label = "auto_sync", "Auto Sync"
                    elif "enrichment" in cmd:
                        ptype, label = "enrichment", "Enrichment"
                    elif "init_brain" in cmd:
                        ptype, label = "init_brain", "Init Brain"
                    elif "weekly_batch" in cmd:
                        ptype, label = "weekly_batch", "Weekly Batch"
                    else:
                        ptype, label = "other_python", "Python"

                # 커맨드라인 미리보기 — 민감 정보 마스킹
                raw_cmd = (p.get("CommandLine") or "")[:200]
                safe_cmd = self._SENSITIVE_RE.sub(r'\1****', raw_cmd)

                # 스크립트명 추출
                script_name = ""
                import re as _re
                if "node" in pname:
                    script_name = label  # Vite 라벨을 script명으로
                else:
                    m = _re.search(r'[\\/]?(\w+)\.py\b', raw_cmd)
                    if m:
                        script_name = m.group(1)
                    elif "-c " in raw_cmd or '"-c"' in raw_cmd:
                        script_name = "inline"

                meta = self._PROC_TYPE_META.get(ptype, {"color": "#9a8e7d", "visible": False})
                # 재시작 target 자동 매핑: ptype 또는 vite_dev_<port>
                # s3_server는 자기 자신 보호 위해 제외 (관리자가 KIS 서버를 재시작하면 이 핸들러가 죽음)
                restart_target = None
                if ptype == "vite_dev":
                    for port in ("5174", "5175", "5176"):
                        if port in pid_ports:
                            restart_target = f"vite_dev_{port}"
                            break
                elif ptype == "slack_bot":
                    restart_target = "slack_bot"
                elif ptype == "issue_backend":
                    restart_target = "issue_backend"
                proc_info = {
                    "pid": pid,
                    "name": p.get("Name", ""),
                    "type": ptype,
                    "label": label,
                    "mem_mb": mem_mb,
                    "cpu": cpu,
                    "created": p.get("Created", ""),
                    "cmd_preview": safe_cmd,
                    "script": script_name,
                    "is_self": pid == my_pid,
                    "status": "normal",  # normal / duplicate / zombie
                    "color": meta["color"],         # 단일 진실 공급원 — 프론트가 그대로 사용
                    "visible_default": meta["visible"],  # 정상 상태일 때 표시 여부
                    "restart_target": restart_target,  # admin 재시작 버튼용 (null이면 미표시)
                }
                seen_types.setdefault(ptype, []).append(proc_info)
                procs.append(proc_info)

            # ── 좀비 판정: python only, vite_dev는 절대 zombie 아님 ──
            zombies = []
            for proc in procs:
                if proc["type"] in ("other_python", "init_brain") and proc["cpu"] > 90:
                    proc["status"] = "zombie"
                    zombies.append(proc["pid"])

            # ── 중복 판정 ──
            # slack_bot: 부모+자식 2개가 정상, 3개+ → 중복
            # s3_server: 관리자+사용자 각각 실행 가능 → 3개+ 일 때만 duplicate
            # vite_dev: 중복 판정 제외 (각 포트별 독립 서버)
            duplicates = []
            warnings = []
            DUP_THRESHOLD = {"slack_bot": 2, "s3_server": 2}
            _DUP_EXEMPT = {"vite_dev", "other_python"}  # 중복 판정 면제 타입
            for ptype, group in seen_types.items():
                if ptype in _DUP_EXEMPT:
                    continue
                threshold = DUP_THRESHOLD.get(ptype)
                if threshold and len(group) > threshold:
                    label = group[0]["label"]
                    warnings.append(
                        f"⚠️ {label} 중복 실행 감지 ({len(group)}개)"
                    )
                    # created 기준 최신 threshold개만 normal, 나머지는 duplicate
                    sorted_grp = sorted(group, key=lambda x: x["created"], reverse=True)
                    for proc in sorted_grp[threshold:]:
                        if not proc["is_self"]:
                            proc["status"] = "duplicate"
                            duplicates.append(proc["pid"])

            # ── 시스템 상태 요약 ──
            system_status = {}
            for ptype in ("slack_bot", "s3_server", "auto_sync", "enrichment"):
                group = seen_types.get(ptype, [])
                normal = [p for p in group if p["status"] == "normal"]
                system_status[ptype] = {
                    "running": len(group) > 0,
                    "count": len(group),
                    "pid": normal[0]["pid"] if normal else None,
                    "mem_mb": normal[0]["mem_mb"] if normal else 0,
                }

            return {
                "processes": procs,
                "warnings": warnings,
                "system_status": system_status,
                "zombies": zombies,
                "duplicates": duplicates,
            }

        except Exception as e:
            return self._empty_processes(str(e))

    @staticmethod
    def _empty_processes(error=None):
        result = {
            "processes": [], "warnings": [], "zombies": [], "duplicates": [],
            "system_status": {
                t: {"running": False, "count": 0, "pid": None, "mem_mb": 0}
                for t in ("slack_bot", "s3_server", "auto_sync", "enrichment")
            },
        }
        if error:
            result["warnings"].append(f"프로세스 조회 실패: {error}")
        return result

    # ── Process Management API (Admin 인증 필요) ───────────
    def _read_json_body(self):
        """POST body를 JSON으로 파싱."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def _check_admin_pw(self, body):
        """Admin 비밀번호 검증. 실패 시 403 응답하고 False 반환."""
        if body.get("password") != ADMIN_PW:
            self._error_json(403, "인증 실패")
            return False
        return True

    def _is_python_process(self, pid):
        """해당 PID가 python.exe/pythonw.exe인지 확인 (안전장치)."""
        try:
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command',
                 f"(Get-Process -Id {pid} -ErrorAction Stop).Name"],
                text=True, timeout=5, creationflags=_NO_WINDOW,
            ).strip().lower()
            return out in ("python", "pythonw")
        except Exception:
            return False

    def _handle_process_kill(self):
        """POST /api/process/kill — 특정 PID Kill (Admin 전용)."""
        body = self._read_json_body()
        if not self._check_admin_pw(body):
            return
        pid = body.get("pid")
        if not pid or pid == os.getpid():
            return self._error_json(400, "유효하지 않은 PID (자기 자신은 Kill 불가)")
        if not self._is_python_process(pid):
            return self._error_json(400, f"PID {pid}는 Python 프로세스가 아닙니다")
        try:
            subprocess.run(
                ['taskkill', '/pid', str(pid), '/f'],
                capture_output=True, timeout=10, creationflags=_NO_WINDOW,
            )
            self._json_response({"success": True, "killed": pid})
        except Exception as e:
            self._error_json(500, f"Kill 실패: {e}")

    def _handle_process_cleanup(self):
        """POST /api/process/cleanup — 중복+좀비 일괄 정리 (Admin 전용)."""
        body = self._read_json_body()
        if not self._check_admin_pw(body):
            return
        proc_data = self._dash_processes()
        targets = proc_data.get("zombies", []) + proc_data.get("duplicates", [])
        # 자기 자신 제외
        targets = [p for p in targets if p != os.getpid()]
        killed = []
        failed = []
        for pid in targets:
            try:
                subprocess.run(
                    ['taskkill', '/pid', str(pid), '/f'],
                    capture_output=True, timeout=10, creationflags=_NO_WINDOW,
                )
                killed.append(pid)
            except Exception:
                failed.append(pid)
        self._json_response({
            "success": True,
            "killed": killed,
            "failed": failed,
            "total_cleaned": len(killed),
        })

    def _handle_process_restart_bot(self):
        """POST /api/process/restart-bot — Slack Bot 전체 종료 후 재실행 (Admin 전용)."""
        body = self._read_json_body()
        if not self._check_admin_pw(body):
            return
        # 1. 기존 slack_bot 프로세스 전부 Kill
        proc_data = self._dash_processes()
        bot_pids = [
            p["pid"] for p in proc_data.get("processes", [])
            if p["type"] == "slack_bot" and not p.get("is_self")
        ]
        for pid in bot_pids:
            try:
                subprocess.run(
                    ['taskkill', '/pid', str(pid), '/f'],
                    capture_output=True, timeout=10, creationflags=_NO_WINDOW,
                )
            except Exception:
                pass

        # 2. 재실행 (venv Python + 프로젝트 루트 cwd로 .env 로딩 보장)
        bot_script = os.path.join(_BOT_SRC, "slack_bot.py")
        if not os.path.exists(bot_script):
            return self._error_json(404, f"slack_bot.py를 찾을 수 없음: {bot_script}")

        venv_python = os.path.join(_PROJECT_ROOT, "venv", "Scripts", "python.exe")
        python_exe = venv_python if os.path.exists(venv_python) else "python"

        # .env는 프로젝트 루트에 위치 → cwd를 루트로 설정
        # slack_bot.py 내부 load_dotenv()가 cwd 기준으로 .env 탐색
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            proc = subprocess.Popen(
                [python_exe, bot_script, '--commands-only'],
                cwd=_PROJECT_ROOT,  # .env가 있는 프로젝트 루트
                env=env,
                creationflags=_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            import time
            time.sleep(4)
            # 재시작 확인: 새 프로세스가 살아있는지 + dashboard 조회
            alive = proc.poll() is None
            new_data = self._dash_processes()
            bot_running = new_data["system_status"]["slack_bot"]["running"]
            self._json_response({
                "success": alive and bot_running,
                "killed_pids": bot_pids,
                "new_pid": proc.pid if alive else None,
                "message": "봇 재시작 완료" if (alive and bot_running) else
                           f"봇 프로세스 시작 실패 (exit={proc.returncode})" if not alive else
                           "봇 재시작 실패 — 프로세스 확인 필요",
            })
        except Exception as e:
            self._error_json(500, f"봇 재실행 실패: {e}")

    # ── 서버 재시작 메타데이터 (단일 진실 공급원) ─────────────────
    # 새 서버 추가 시 여기 한 곳만 등록
    _RESTART_TARGETS = {
        "slack_bot": {
            "label": "Slack Bot",
            "kill_type": "slack_bot",
            "exec": ["{venv_python}", "{root}/Slack Bot/slack_bot.py", "--commands-only"],
            "cwd": "{root}",
        },
        "s3_server": {
            "label": "KIS Server",
            "kill_type": None,  # 자기 자신은 죽이지 않음 (요청자 PID 보호)
            "exec": ["{venv_pythonw}", "{root}/tools/s3_server.py", "--port", "9091", "--silent"],
            "cwd": "{root}/tools",
        },
        "vite_dev_5174": {
            "label": "QA 대시보드",
            "kill_port": 5174,
            "exec": ["cmd", "/c", "npm", "run", "dev"],
            "cwd": "D:/Vibe Dev/Issue Dashboard",
        },
        "vite_dev_5175": {
            "label": "에이전트 팀",
            "kill_port": 5175,
            "exec": ["cmd", "/c", "npm", "run", "dev", "--", "--port", "5175"],
            "cwd": "D:/Vibe Dev/QA Ops/agent-dashboard",
        },
        "vite_dev_5176": {
            "label": "QA Workflow",
            "kill_port": 5176,
            "exec": ["cmd", "/c", "pm2", "restart", "all"],
            "cwd": "D:/Vibe Dev/QA Workflow",
        },
        "issue_backend": {
            "label": "Issue Dashboard API",
            "kill_port": 9100,
            "exec": ["{venv_pythonw}", "D:/Vibe Dev/Issue Dashboard/server/server.py", "--port", "9100"],
            "cwd": "D:/Vibe Dev/Issue Dashboard",
        },
    }

    def _handle_server_restart(self):
        """POST /api/server/restart — 지정 서버 종료 후 재실행 (Admin 전용).

        Body: {"password": "...", "target": "slack_bot" | "s3_server" | "vite_dev_5174" ...}
        """
        body = self._read_json_body()
        if not self._check_admin_pw(body):
            return
        target = body.get("target", "")
        cfg = self._RESTART_TARGETS.get(target)
        if not cfg:
            self._error_json(400, f"알 수 없는 target: {target}")
            return

        # slack_bot은 기존 전용 핸들러 위임 (검증된 경로 유지)
        if target == "slack_bot":
            return self._handle_process_restart_bot()

        killed_pids = []

        # ── Step 1: 종료 ──
        if cfg.get("kill_port"):
            try:
                ps_kill = (
                    f"Get-NetTCPConnection -State Listen -LocalPort {cfg['kill_port']} "
                    "-ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique"
                )
                out = subprocess.check_output(
                    ['powershell', '-NoProfile', '-Command', ps_kill],
                    text=True, timeout=8, creationflags=_NO_WINDOW,
                ).strip()
                for line in out.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        pid_kill = int(line)
                        try:
                            subprocess.run(
                                ['taskkill', '/pid', str(pid_kill), '/f', '/t'],
                                capture_output=True, timeout=10, creationflags=_NO_WINDOW,
                            )
                            killed_pids.append(pid_kill)
                        except Exception:
                            pass
            except Exception:
                pass
        elif cfg.get("kill_type"):
            proc_data = self._dash_processes()
            for p in proc_data.get("processes", []):
                if p["type"] == cfg["kill_type"] and not p.get("is_self"):
                    try:
                        subprocess.run(
                            ['taskkill', '/pid', str(p["pid"]), '/f'],
                            capture_output=True, timeout=10, creationflags=_NO_WINDOW,
                        )
                        killed_pids.append(p["pid"])
                    except Exception:
                        pass

        # ── Step 2: 재실행 ──
        venv_python = os.path.join(_PROJECT_ROOT, "venv", "Scripts", "python.exe")
        venv_pythonw = os.path.join(_PROJECT_ROOT, "venv", "Scripts", "pythonw.exe")
        substitutions = {
            "venv_python": venv_python if os.path.exists(venv_python) else "python",
            "venv_pythonw": venv_pythonw if os.path.exists(venv_pythonw) else "pythonw",
            "root": _PROJECT_ROOT,
        }

        def _sub(s):
            return s.format(**substitutions) if isinstance(s, str) else s

        cmd_list = [_sub(c) for c in cfg["exec"]]
        cwd = _sub(cfg["cwd"])

        try:
            # 서버 시작은 WMI 방식 (콘솔 창 없음, 부모-자식 분리)
            ps_create = (
                "$wmi = [wmiclass]'Win32_Process'; "
                f"$r = $wmi.Create('{' '.join(cmd_list).replace(chr(39), chr(92)+chr(39))}', '{cwd.replace(chr(39), chr(92)+chr(39))}'); "
                "$r.ProcessId"
            )
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command', ps_create],
                text=True, timeout=15, creationflags=_NO_WINDOW,
            ).strip()
            new_pid = int(out) if out.isdigit() else None
        except Exception as e:
            self._error_json(500, f"{cfg['label']} 재시작 실패: {e}")
            return

        self._json_response({
            "success": new_pid is not None,
            "target": target,
            "label": cfg["label"],
            "killed_pids": killed_pids,
            "new_pid": new_pid,
            "message": f"{cfg['label']} 재시작 완료 (PID: {new_pid})" if new_pid else f"{cfg['label']} 재시작 실패",
        })

    def _handle_server_shutdown(self):
        """POST /api/server/shutdown — 자기 서버 프로세스 종료 (localhost 전용)."""
        # localhost에서만 허용
        client_ip = self.client_address[0]
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            return self._error_json(403, "localhost에서만 종료 가능")
        self._json_response({"success": True, "message": "서버를 종료합니다"})
        # 응답 전송 후 종료
        import time
        def _delayed_exit():
            time.sleep(0.5)
            os._exit(0)
        t = threading.Thread(target=_delayed_exit, daemon=True)
        t.start()

    # ── 브라우저 heartbeat (중앙 서버: 사용자 식별) ──────────────────
    def _handle_browser_heartbeat(self):
        """POST /api/heartbeat — 브라우저에서 직접 heartbeat 수신."""
        body = self._read_json_body()
        client_id = body.get("client_id", "")
        if not client_id:
            self._error_json(400, "client_id 필수")
            return
        # XSS 방어: 이름 strip + 길이 제한
        raw_name = body.get("user_name", "Unknown")
        user_name = str(raw_name).strip()[:50] or "Unknown"
        client_ip = self.client_address[0]
        with _clients_lock:
            _connected_clients[client_id] = {
                "user": user_name,
                "ip": client_ip,
                "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active",
            }
            if client_id in _disconnect_queue:
                _disconnect_queue.discard(client_id)
                _connected_clients.pop(client_id, None)
                self._json_response({"action": "shutdown"})
                return
        self._json_response({"action": "ack"})

    def _handle_browser_leave(self):
        """POST /api/heartbeat/leave — 탭 닫기/연결 해제 시 즉시 클라이언트 제거."""
        body = self._read_json_body()
        client_id = body.get("client_id", "")
        if not client_id:
            self._error_json(400, "client_id 필수")
            return
        with _clients_lock:
            _connected_clients.pop(client_id, None)
        self._json_response({"action": "ack"})

    # ── Heartbeat System (Admin 서버: 접속자 추적) ──────────
    def _handle_admin_heartbeat(self):
        """POST /api/admin/heartbeat — 클라이언트 상태 등록/갱신."""
        body = self._read_json_body()
        client_id = body.get("client_id", "")
        if not client_id:
            return self._error_json(400, "client_id 필수")

        action = body.get("action", "heartbeat")
        client_ip = self.client_address[0]

        with _clients_lock:
            if action == "disconnect":
                _connected_clients.pop(client_id, None)
                self._json_response({"action": "ack"})
                return

            _connected_clients[client_id] = {
                "user": body.get("user_name", "Unknown"),
                "ip": client_ip,
                "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active",
            }

            # 강제 종료 큐 확인
            if client_id in _disconnect_queue:
                _disconnect_queue.discard(client_id)
                _connected_clients.pop(client_id, None)
                self._json_response({"action": "shutdown"})
                return

        self._json_response({"action": "ack"})

    def _handle_admin_clients(self):
        """GET /api/admin/clients — 접속자 리스트."""
        now = datetime.now()
        clients = []
        with _clients_lock:
            for cid, info in list(_connected_clients.items()):
                try:
                    last = datetime.strptime(info["last_seen"], "%Y-%m-%d %H:%M:%S")
                    age_sec = (now - last).total_seconds()
                except Exception:
                    age_sec = 9999
                # 60초 이상 무응답이면 비활성
                status = "active" if age_sec < 60 else "inactive"
                # _SESSION_TIMEOUT_SEC * 2 이상 무응답이면 자동 제거
                if age_sec > _SESSION_TIMEOUT_SEC * 2:
                    _connected_clients.pop(cid, None)
                    continue
                clients.append({
                    "client_id": cid,
                    "user": info["user"],
                    "ip": info["ip"],
                    "last_seen": info["last_seen"],
                    "age_sec": int(age_sec),
                    "status": status,
                })
        active = sum(1 for c in clients if c["status"] == "active")
        self._json_response({
            "clients": clients,
            "active_count": active,
            "inactive_count": len(clients) - active,
            "total_count": len(clients),
        })

    def _handle_admin_disconnect(self):
        """POST /api/admin/disconnect — 강제 연결 해제 시그널 (Admin 전용)."""
        body = self._read_json_body()
        if not self._check_admin_pw(body):
            return
        client_id = body.get("client_id")
        if not client_id:
            return self._error_json(400, "client_id 필수")
        if client_id == "all":
            with _clients_lock:
                for cid in list(_connected_clients.keys()):
                    _disconnect_queue.add(cid)
            self._json_response({"success": True, "message": "전체 연결 해제 시그널 전송"})
        else:
            _disconnect_queue.add(client_id)
            self._json_response({"success": True, "message": f"{client_id} 연결 해제 시그널 전송"})

    def _json_response(self, data, code=200):
        """JSON 응답 헬퍼."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ── Dashboard: Section 8 — Token Usage ─────────────────
    def _dash_token_usage(self):
        """token_usage.log에서 API 토큰 사용량 집계."""
        log_path = os.path.join(_LOGS_DIR, "token_usage.log")
        lines = self._tail_file(log_path, 500)
        if not lines:
            return {"total_calls": 0, "total_input": 0, "total_output": 0,
                    "by_source": {}, "by_date": {}}

        total_calls = 0
        total_input = 0
        total_output = 0
        by_source = {}  # source -> {calls, input, output}
        by_date = {}    # YYYY-MM-DD -> {calls, input, output}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 형식: 2026-03-13 17:30:44 | wiki | in=1234 | out=567 | total=1801
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            try:
                ts = parts[0]
                source = parts[1].strip()
                in_tok = int(parts[2].split("=")[1])
                out_tok = int(parts[3].split("=")[1])

                total_calls += 1
                total_input += in_tok
                total_output += out_tok

                # 소스별
                if source not in by_source:
                    by_source[source] = {"calls": 0, "input": 0, "output": 0}
                by_source[source]["calls"] += 1
                by_source[source]["input"] += in_tok
                by_source[source]["output"] += out_tok

                # 날짜별
                date_key = ts[:10]
                if date_key not in by_date:
                    by_date[date_key] = {"calls": 0, "input": 0, "output": 0}
                by_date[date_key]["calls"] += 1
                by_date[date_key]["input"] += in_tok
                by_date[date_key]["output"] += out_tok
            except (ValueError, IndexError):
                continue

        return {
            "total_calls": total_calls,
            "total_input": total_input,
            "total_output": total_output,
            "by_source": by_source,
            "by_date": by_date,
        }

    # ── Dashboard 유틸 ────────────────────────────────────
    @staticmethod
    def _tail_file(filepath, max_lines=100):
        """파일 끝에서 max_lines줄 읽기. 파일이 없으면 빈 리스트."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-max_lines:]
        except Exception:
            return []

    # ── Helpers ──────────────────────────────────────────────
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _error_json(self, code, msg):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ── Ops Metrics API ────────────────────────────────────
    def _handle_ops_metrics(self):
        """시스템 운영 지표 JSON 응답."""
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "cache_efficiency": self._ops_cache_efficiency(),
            "response_summary": self._ops_response_summary(),
            "daily_trend": self._ops_daily_trend(),
            "recent_failures": self._ops_recent_failures(),
            "system_design_check": self._ops_design_check(),
        }
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ── Brain Metrics API ──────────────────────────────────
    def _handle_brain_metrics(self):
        """Prompt Cultivation Brain 성장 메트릭스 JSON 응답."""
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "brain_available": False,
        }
        if not os.path.exists(_BRAIN_DB):
            result["error"] = f"brain.db not found: {_BRAIN_DB}"
            self._json_response(result)
            return
        try:
            conn = sqlite3.connect(_BRAIN_DB, timeout=5)
            conn.row_factory = sqlite3.Row
            result["brain_available"] = True

            # ── overview ──
            overview = {}
            overview["total_experiences"] = conn.execute(
                "SELECT COUNT(*) FROM experiences"
            ).fetchone()[0]
            overview["active_experiences"] = conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE status='active'"
            ).fetchone()[0]
            overview["archived_experiences"] = conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE status='archived'"
            ).fetchone()[0]
            overview["personality_count"] = conn.execute(
                "SELECT COUNT(*) FROM personality_memory WHERE status='active'"
            ).fetchone()[0]
            overview["audit_log_count"] = conn.execute(
                "SELECT COUNT(*) FROM audit_log"
            ).fetchone()[0]
            row = conn.execute(
                "SELECT AVG(importance) as v FROM experiences WHERE status='active'"
            ).fetchone()
            overview["avg_importance"] = round(row["v"], 3) if row["v"] else 0.0
            row = conn.execute(
                "SELECT AVG(effectiveness) as v FROM experiences WHERE status='active'"
            ).fetchone()
            overview["avg_effectiveness"] = round(row["v"], 3) if row["v"] else 0.0
            result["overview"] = overview

            # ── daily_accumulation (최근 30일) ──
            rows = conn.execute(
                "SELECT date(created_at) as d, COUNT(*) as cnt "
                "FROM experiences GROUP BY d ORDER BY d DESC LIMIT 30"
            ).fetchall()
            result["daily_accumulation"] = [
                {"date": r["d"], "count": r["cnt"]} for r in rows
            ]

            # ── daily_journal (최근 30일 journal 기록 추적) ──
            j_rows = conn.execute(
                "SELECT date(date) as d, COUNT(*) as cnt "
                "FROM dev_journal "
                "WHERE date >= date('now', '-30 days') "
                "GROUP BY d ORDER BY d ASC"
            ).fetchall()
            # 30일 캘린더 생성 (기록 있는 날 / 없는 날)
            from datetime import date as _date
            today = _date.today()
            journal_map = {r["d"]: r["cnt"] for r in j_rows}
            daily_journal = []
            for i in range(29, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                daily_journal.append({"date": d, "count": journal_map.get(d, 0)})
            result["daily_journal"] = daily_journal

            # ── effectiveness_distribution ──
            rows = conn.execute(
                "SELECT "
                "  CASE "
                "    WHEN applied_count = 0 THEN 'untested' "
                "    WHEN effectiveness >= 0.7 THEN 'high' "
                "    WHEN effectiveness >= 0.4 THEN 'medium' "
                "    ELSE 'low' "
                "  END as band, COUNT(*) as cnt "
                "FROM experiences WHERE status='active' "
                "GROUP BY band"
            ).fetchall()
            eff_dist = {"high": 0, "medium": 0, "low": 0, "untested": 0}
            for r in rows:
                eff_dist[r["band"]] = r["cnt"]
            result["effectiveness_distribution"] = eff_dist

            # ── category_breakdown ──
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt "
                "FROM experiences WHERE status='active' "
                "GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
            result["category_breakdown"] = {r["category"]: r["cnt"] for r in rows}

            # ── l1_synthesis ──
            l1 = {}
            rows_l1 = conn.execute(
                "SELECT * FROM personality_memory WHERE status='active'"
            ).fetchall()
            l1["total_beliefs"] = len(rows_l1)
            l1["active_beliefs"] = len(rows_l1)
            if rows_l1:
                l1["avg_confidence"] = round(
                    sum(r["confidence"] for r in rows_l1) / len(rows_l1), 3
                )
                l1["avg_evidence_count"] = round(
                    sum(r["evidence_count"] for r in rows_l1) / len(rows_l1), 1
                )
                domains = {}
                for r in rows_l1:
                    d = r["domain"] or "unknown"
                    domains[d] = domains.get(d, 0) + 1
                l1["domains"] = domains
            else:
                l1["avg_confidence"] = 0.0
                l1["avg_evidence_count"] = 0.0
                l1["domains"] = {}
            result["l1_synthesis"] = l1

            # ── weekly_batch ──
            wb = {}
            row = conn.execute(
                "SELECT MAX(created_at) as last_at FROM audit_log "
                "WHERE agent IN ('auditor','synthesizer')"
            ).fetchone()
            last_at = row["last_at"] if row and row["last_at"] else None
            wb["last_run"] = last_at
            if last_at:
                try:
                    last_dt = datetime.strptime(last_at[:19], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    try:
                        last_dt = datetime.strptime(last_at[:19], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        last_dt = None
                if last_dt:
                    days = (datetime.now() - last_dt).days
                    wb["days_since_last_run"] = days
                    wb["status"] = "ok" if days <= 7 else ("warning" if days <= 14 else "critical")
                else:
                    wb["days_since_last_run"] = -1
                    wb["status"] = "unknown"
            else:
                wb["days_since_last_run"] = -1
                wb["status"] = "unknown"

            # 마지막 배치 결과
            row = conn.execute(
                "SELECT action, COUNT(*) as cnt FROM audit_log "
                "WHERE agent='auditor' AND created_at >= date('now', '-7 days') "
                "GROUP BY action"
            ).fetchall()
            wb["last_archived"] = sum(r["cnt"] for r in row if r["action"] == "archived")
            row2 = conn.execute(
                "SELECT COUNT(*) as cnt FROM audit_log "
                "WHERE agent='synthesizer' AND created_at >= date('now', '-7 days')"
            ).fetchone()
            wb["last_synthesized"] = row2["cnt"] if row2 else 0
            result["weekly_batch"] = wb

            # ── recent_activity (최근 10건) ──
            rows = conn.execute(
                "SELECT created_at, agent, action, target_type, target_id, reason "
                "FROM audit_log ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            result["recent_activity"] = [
                {
                    "at": r["created_at"],
                    "agent": r["agent"],
                    "action": r["action"],
                    "target": f"{r['target_type']} #{r['target_id']}" if r["target_id"] else r["target_type"],
                    "reason": r["reason"],
                }
                for r in rows
            ]

            # ── pending_tasks (미완료/보류 작업) ──
            try:
                rows = conn.execute(
                    "SELECT id, title, description, status, priority, source, domain, "
                    "created_at, updated_at FROM pending_tasks "
                    "WHERE status IN ('pending', 'deferred') "
                    "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                    "created_at DESC"
                ).fetchall()
                result["pending_tasks"] = [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "description": r["description"],
                        "status": r["status"],
                        "priority": r["priority"],
                        "source": r["source"],
                        "domain": r["domain"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
            except sqlite3.OperationalError:
                result["pending_tasks"] = []

            # ── health_score (0~100) — brain_health.py SSOT ──
            try:
                import importlib.util
                _health_spec = importlib.util.spec_from_file_location(
                    "brain_health",
                    os.path.join(
                        os.environ.get("USERPROFILE", os.environ.get("HOME", "")),
                        ".claude", "hooks", "brain_health.py",
                    ),
                )
                _health_mod = importlib.util.module_from_spec(_health_spec)
                _health_spec.loader.exec_module(_health_mod)
                result["health"] = _health_mod.compute_health(conn)
            except Exception:
                # fallback: SSOT 모듈 로드 실패 시 빈 health
                result["health"] = {"score": 0, "level": "Unknown"}

            conn.close()
        except Exception as e:
            result["error"] = str(e)

        self._json_response(result)

    # ══════════════════════════════════════════════════════════════
    # Claude Monitoring API
    # ══════════════════════════════════════════════════════════════

    def _handle_claude_metrics(self):
        """Claude 모니터링 전체 메트릭 JSON 응답.
        단일 파싱 원칙: config, bot_tokens, cc_data를 1회만 생성 후 재활용."""
        try:
            cfg = self._load_claude_config()
            bot_tokens = self._parse_bot_tokens()
            cc_data = self._parse_all_session_meta(cfg)

            result = {
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "token_usage": self._build_token_usage(bot_tokens, cc_data),
                "sessions": self._build_sessions(cc_data),
                "system_status": self._claude_system_status(cfg),
                "performance": self._claude_performance(cc_data),
                "cost_budget": self._build_cost_budget(bot_tokens, cc_data, cfg),
            }
            self._json_response(result)
        except Exception as e:
            self._json_response({"error": str(e)[:200],
                                 "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}, code=500)

    # ── Claude: Bot 토큰 로그 파싱 (1회) ────────────────────
    def _parse_bot_tokens(self):
        """token_usage.log를 1회 파싱하여 기간별/소스별 집계 반환."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        r = {"today": {"input": 0, "output": 0, "calls": 0},
             "month": {"input": 0, "output": 0, "calls": 0},
             "week": {"input": 0, "output": 0, "calls": 0},
             "by_source": {}, "by_date": {},
             "today_str": today_str, "month_str": month_str}
        log_path = os.path.join(_LOGS_DIR, "token_usage.log")
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) < 4:
                        continue
                    try:
                        ts = parts[0]
                        date_key = ts[:10]
                        if not date_key.startswith(month_str):
                            continue
                        source = parts[1].strip()
                        in_tok = int(parts[2].split("=")[1])
                        out_tok = int(parts[3].split("=")[1])

                        r["month"]["input"] += in_tok
                        r["month"]["output"] += out_tok
                        r["month"]["calls"] += 1

                        if date_key == today_str:
                            r["today"]["input"] += in_tok
                            r["today"]["output"] += out_tok
                            r["today"]["calls"] += 1
                        if date_key >= week_ago:
                            r["week"]["input"] += in_tok
                            r["week"]["output"] += out_tok
                            r["week"]["calls"] += 1

                        r["by_source"].setdefault(source, {"input": 0, "output": 0, "calls": 0})
                        r["by_source"][source]["input"] += in_tok
                        r["by_source"][source]["output"] += out_tok
                        r["by_source"][source]["calls"] += 1

                        if date_key >= week_ago:
                            r["by_date"].setdefault(date_key, {"input": 0, "output": 0, "calls": 0})
                            r["by_date"][date_key]["input"] += in_tok
                            r["by_date"][date_key]["output"] += out_tok
                            r["by_date"][date_key]["calls"] += 1
                    except (ValueError, IndexError):
                        continue
        except Exception:
            pass
        return r

    # ── Claude: Session-meta 전체 파싱 (1회) ──────────────────
    def _parse_all_session_meta(self, cfg):
        """session-meta/*.json을 1회 파싱하여 토큰/세션/비용에 필요한 데이터 반환."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        max_days = cfg.get("session_meta_max_days", 90)
        cutoff_ts = (now - timedelta(days=max_days)).timestamp()

        result = {
            "sessions": [],  # 전체 세션 정보 목록 (파싱된 데이터)
            "token_agg": {    # 토큰 집계
                "today": {"input": 0, "output": 0, "sessions": 0},
                "month": {"input": 0, "output": 0, "sessions": 0},
                "week": {"input": 0, "output": 0, "sessions": 0},
                "by_model": {}, "by_date": {},
            },
            "parse_errors": 0,
        }

        if not os.path.isdir(_SESSION_META_DIR):
            return result

        try:
            entries = sorted(
                [e for e in os.scandir(_SESSION_META_DIR)
                 if e.is_file() and e.name.endswith(".json")
                 and e.stat().st_mtime >= cutoff_ts],
                key=lambda e: e.stat().st_mtime, reverse=True
            )
        except OSError:
            return result

        ta = result["token_agg"]

        for entry in entries:
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                result["parse_errors"] += 1
                continue

            in_tok = data.get("input_tokens", 0) or 0
            out_tok = data.get("output_tokens", 0) or 0
            model = data.get("model", "unknown")
            dur = data.get("duration_minutes", 0) or 0

            # 날짜 추출
            ts_field = data.get("timestamp") or data.get("first_interaction_timestamp")
            if ts_field and isinstance(ts_field, str):
                session_date = ts_field[:10]
            else:
                session_date = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d")

            # first_prompt 마스킹: 앞 30자만
            raw_prompt = data.get("first_prompt") or ""
            prompt = raw_prompt[:30] + ("..." if len(raw_prompt) > 30 else "")

            # 세션 정보 저장
            result["sessions"].append({
                "id": entry.name.replace(".json", "")[:12],
                "date": session_date,
                "duration_min": round(dur, 1),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "model": model,
                "prompt_preview": prompt,
                "tools": data.get("tool_counts", {}),
                "tool_errors": data.get("tool_errors", 0),
                "user_interruptions": data.get("user_interruptions", 0),
            })

            # 토큰 집계 — 모델별
            ta["by_model"].setdefault(model, {"input": 0, "output": 0, "sessions": 0})
            ta["by_model"][model]["input"] += in_tok
            ta["by_model"][model]["output"] += out_tok
            ta["by_model"][model]["sessions"] += 1

            # 기간별
            if session_date and session_date.startswith(month_str):
                ta["month"]["input"] += in_tok
                ta["month"]["output"] += out_tok
                ta["month"]["sessions"] += 1
            if session_date == today_str:
                ta["today"]["input"] += in_tok
                ta["today"]["output"] += out_tok
                ta["today"]["sessions"] += 1
            if session_date and session_date >= week_ago:
                ta["week"]["input"] += in_tok
                ta["week"]["output"] += out_tok
                ta["week"]["sessions"] += 1
                ta["by_date"].setdefault(session_date, {"input": 0, "output": 0, "sessions": 0})
                ta["by_date"][session_date]["input"] += in_tok
                ta["by_date"][session_date]["output"] += out_tok
                ta["by_date"][session_date]["sessions"] += 1

        return result

    # ── Claude: 빌더 — Token Usage ────────────────────────────
    @staticmethod
    def _build_token_usage(bot_tokens, cc_data):
        return {"bot": bot_tokens, "cc": cc_data["token_agg"],
                "disclaimer": "로컬 커맨드 기준 추정치 (Railway 제외)"}

    # ── Claude: 빌더 — Sessions ───────────────────────────────
    @staticmethod
    def _build_sessions(cc_data):
        today_str = datetime.now().strftime("%Y-%m-%d")
        sessions = cc_data["sessions"]
        today_count = sum(1 for s in sessions if s["date"] == today_str)
        durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
        avg_dur = round(sum(durations) / len(durations), 1) if durations else 0

        return {
            "active": 0,  # system_status.cc_process_count로 대체 (프론트에서 사용)
            "today_count": today_count,
            "avg_duration_min": avg_dur,
            "recent": sessions[:10],
            "parse_errors": cc_data["parse_errors"],
        }

    # ── Claude: System Status ─────────────────────────────────
    def _claude_system_status(self, cfg):
        """MCP 서버 ping + 로컬 HTTP 서버 헬스체크 (병렬) + 프로세스 탐지."""
        mcp_results = []
        local_results = []
        ping_timeout = cfg.get("mcp_ping_timeout_sec", 3)
        local_timeout = 2  # 로컬 서버 헬스체크 타임아웃

        def _ping_mcp(name, url):
            import time as _time
            start = _time.time()
            try:
                req = urllib.request.Request(url, method="POST",
                    headers={"Content-Type": "application/json"},
                    data=b'{"jsonrpc":"2.0","method":"ping","id":1}')
                with urllib.request.urlopen(req, timeout=ping_timeout) as resp:
                    latency = int((_time.time() - start) * 1000)
                    status = "up" if resp.status < 400 else "degraded"
                    return {"name": name, "url": url, "status": status,
                            "latency_ms": latency, "category": "mcp"}
            except Exception as e:
                latency = int((_time.time() - start) * 1000)
                return {"name": name, "url": url, "status": "down",
                        "latency_ms": latency, "error": str(e)[:80],
                        "category": "mcp"}

        def _ping_local(name, info):
            import time as _time
            url = info["url"]
            start = _time.time()
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=local_timeout) as resp:
                    latency = int((_time.time() - start) * 1000)
                    status = "up" if resp.status < 400 else "degraded"
                    return {"name": name, "url": url, "status": status,
                            "latency_ms": latency, "desc": info["desc"],
                            "optional": info.get("optional", False),
                            "category": "local"}
            except Exception as e:
                latency = int((_time.time() - start) * 1000)
                return {"name": name, "url": url, "status": "down",
                        "latency_ms": latency, "error": str(e)[:80],
                        "desc": info["desc"],
                        "optional": info.get("optional", False),
                        "category": "local"}

        # MCP + 로컬 서버를 모두 병렬 처리 (max_workers=총 대상 수)
        total_targets = len(_MCP_ENDPOINTS) + len(_LOCAL_SERVERS)
        try:
            with ThreadPoolExecutor(max_workers=total_targets) as ex:
                futures = {}
                for name, url in _MCP_ENDPOINTS.items():
                    futures[ex.submit(_ping_mcp, name, url)] = ("mcp", name)
                for name, info in _LOCAL_SERVERS.items():
                    futures[ex.submit(_ping_local, name, info)] = ("local", name)

                for f in as_completed(futures, timeout=max(ping_timeout, local_timeout) + 2):
                    try:
                        result = f.result()
                        if result["category"] == "mcp":
                            mcp_results.append(result)
                        else:
                            local_results.append(result)
                    except Exception:
                        cat, name = futures[f]
                        if cat == "mcp":
                            mcp_results.append({"name": name, "status": "timeout",
                                                "latency_ms": ping_timeout * 1000,
                                                "category": "mcp"})
                        else:
                            info = _LOCAL_SERVERS.get(name, {})
                            local_results.append({"name": name, "status": "timeout",
                                                  "latency_ms": local_timeout * 1000,
                                                  "desc": info.get("desc", ""),
                                                  "optional": info.get("optional", False),
                                                  "category": "local"})
        except Exception:
            # as_completed TimeoutError — 미완료 future 처리
            completed_names = {r["name"] for r in mcp_results + local_results}
            for name in _MCP_ENDPOINTS:
                if name not in completed_names:
                    mcp_results.append({"name": name, "status": "timeout",
                                        "latency_ms": ping_timeout * 1000,
                                        "category": "mcp"})
            for name, info in _LOCAL_SERVERS.items():
                if name not in completed_names:
                    local_results.append({"name": name, "status": "timeout",
                                          "latency_ms": local_timeout * 1000,
                                          "desc": info["desc"],
                                          "optional": info.get("optional", False),
                                          "category": "local"})

        # 프로세스 탐지 — node.exe(Claude Code) + python.exe
        processes = {"claude_code": [], "python": []}
        warnings = []
        try:
            ps_cmd = (
                "$portMap = @{}; "
                "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $portMap[$_.OwningProcess] = ($portMap[$_.OwningProcess] + ',' + $_.LocalPort).TrimStart(',') }; "
                "Get-CimInstance Win32_Process "
                "-Filter \"name='node.exe' or name='python.exe' or name='pythonw.exe'\" "
                "| ForEach-Object { "
                "  $cpu = try { (Get-Process -Id $_.ProcessId -ErrorAction Stop).CPU } catch { 0 }; "
                "  [pscustomobject]@{ "
                "    ProcessId=$_.ProcessId; Name=$_.Name; "
                "    MemMB=[math]::Round($_.WorkingSetSize/1MB,1); "
                "    CPU=[math]::Round($cpu,1); "
                "    CommandLine=$_.CommandLine; "
                "    Created=$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'); "
                "    Ports=($portMap[$_.ProcessId] -join ',') "
                "  } "
                "} | ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                text=True, timeout=10, creationflags=_NO_WINDOW,
            ).strip()
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                _sensitive_re = getattr(self, '_SENSITIVE_RE', None)
                for p in data:
                    cmd = (p.get("CommandLine") or "").lower()
                    pname = (p.get("Name") or "").lower()
                    pid = p.get("ProcessId", 0)
                    mem_mb = p.get("MemMB", 0)
                    ports = str(p.get("Ports") or "")

                    raw_cmd = (p.get("CommandLine") or "")[:120]
                    if _sensitive_re:
                        safe_cmd = _sensitive_re.sub(r'\1****', raw_cmd)
                    else:
                        safe_cmd = re.sub(
                            r'((?:--?)?(?:token|key|password|secret|api.?key)\s*[=:\s])\S+',
                            r'\1****', raw_cmd, flags=re.IGNORECASE)

                    if "node" in pname and ("claude" in cmd or ".claude" in cmd):
                        processes["claude_code"].append({
                            "pid": pid, "mem_mb": mem_mb,
                            "created": p.get("Created", ""),
                            "cmd_preview": safe_cmd,
                            "desc": _PROCESS_DESC["claude_code"],
                        })
                    elif "node" in pname and any(pt in ports for pt in ("5174", "5175", "5176")):
                        # Vite dev 서버: 실제 리스닝 포트 기반 라벨링
                        if "5175" in ports:
                            vdesc = "에이전트 팀 (5175)"
                        elif "5176" in ports:
                            vdesc = "QA Workflow (5176)"
                        else:
                            vdesc = "QA 대시보드 (5174)"
                        processes["python"].append({
                            "pid": pid, "type": "vite_dev", "mem_mb": mem_mb,
                            "created": p.get("Created", ""),
                            "cmd_preview": safe_cmd,
                            "desc": vdesc,
                        })
                    elif "python" in pname:
                        if "slack_bot" in cmd:
                            ptype = "slack_bot"
                        elif "s3_server" in cmd:
                            ptype = "s3_server"
                        elif "auto_sync" in cmd:
                            ptype = "auto_sync"
                        else:
                            ptype = "other"
                        processes["python"].append({
                            "pid": pid, "type": ptype, "mem_mb": mem_mb,
                            "created": p.get("Created", ""),
                            "cmd_preview": safe_cmd,
                            "desc": _PROCESS_DESC.get(ptype, "Python 프로세스"),
                        })
        except Exception as e:
            warnings.append(f"프로세스 조회 실패: {str(e)[:60]}")

        mcp_up = sum(1 for m in mcp_results if m["status"] == "up")
        mcp_total = len(mcp_results)
        # 로컬 서버: optional=True인 서버는 카운트에서 제외
        local_required = [s for s in local_results if not s.get("optional")]
        local_up = sum(1 for s in local_required if s["status"] == "up")
        local_total = len(local_required)

        return {
            "mcp_servers": mcp_results,
            "mcp_summary": f"{mcp_up}/{mcp_total}",
            "local_servers": local_results,
            "local_summary": f"{local_up}/{local_total}",
            "processes": processes,
            "cc_process_count": len(processes["claude_code"]),
            "warnings": warnings,
        }

    # ── Claude: Performance ───────────────────────────────────
    _RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

    @staticmethod
    def _raise_risk(current, new_level):
        """리스크 레벨 상향 (unknown < low < medium < high).
        unknown은 데이터 부재 상태로, low보다 낮은 우선순위."""
        order = {"unknown": -1, "low": 0, "medium": 1, "high": 2}
        return new_level if order.get(new_level, -1) > order.get(current, -1) else current

    def _claude_performance(self, cc_data=None):
        """Claude 자체 성능 + MCP 운영 지표 → 종합 리스크 판정.

        두 영역을 분리하여 각각 독립 리스크 판정 후 max()로 종합.
        - claude_self: session-meta 기반 (토큰 트렌드, 세션 시간, 도구 에러, 중단율)
        - mcp_ops: ops_metrics.db 기반 (전체 소스 p99, 에러율, 캐시 적중률)
        """
        result = {
            "claude_self": self._perf_claude_self(cc_data),
            "mcp_ops": self._perf_mcp_ops(),
        }
        # 종합 리스크 = max(claude_self, mcp_ops); unknown은 무시하고 유효 레벨 우선
        cr = result["claude_self"].get("risk_level", "unknown")
        mr = result["mcp_ops"].get("risk_level", "unknown")
        result["risk_level"] = self._raise_risk(cr, mr)
        result["concerns"] = (result["claude_self"].get("concerns", [])
                               + result["mcp_ops"].get("concerns", []))
        return result

    def _perf_claude_self(self, cc_data=None):
        """Claude 자체 성능 지표 — session-meta 기반 분석.

        측정 항목:
        - avg_tokens_per_session: 세션당 평균 토큰 (입력+출력)
        - token_trend_pct: 최근 3일 vs 이전 4일 토큰 소모 증가율(%)
        - avg_session_min: 평균 세션 시간(분)
        - tool_error_rate: 도구 호출 대비 에러 비율(%)
        - interruption_rate: 사용자 인터럽션 비율(%)
        """
        r = {"risk_level": "low", "concerns": [], "confidence": "normal",
             "avg_tokens_per_session": 0, "token_trend_pct": 0,
             "avg_session_min": 0, "tool_error_rate": 0,
             "interruption_rate": 0, "sample_count": 0}

        sessions = (cc_data or {}).get("sessions", [])
        if not sessions:
            r["confidence"] = "no_data"
            r["risk_level"] = "unknown"
            return r

        r["sample_count"] = len(sessions)
        if len(sessions) < 5:
            r["confidence"] = "insufficient"

        # ── 세션당 평균 토큰 ─────────────────────────
        total_tokens = [(s["input_tokens"] + s["output_tokens"]) for s in sessions]
        r["avg_tokens_per_session"] = round(sum(total_tokens) / len(total_tokens))

        # ── 토큰 트렌드 (최근 3일 vs 이전 4일) ──────
        now = datetime.now()
        d3 = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        d7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [t for s, t in zip(sessions, total_tokens)
                  if (s.get("date") or "") >= d3]
        older = [t for s, t in zip(sessions, total_tokens)
                 if d7 <= (s.get("date") or "") < d3]
        if recent and older:
            avg_recent = sum(recent) / len(recent)
            avg_older = sum(older) / len(older)
            if avg_older > 0:
                r["token_trend_pct"] = round(
                    (avg_recent - avg_older) / avg_older * 100, 1)

        # ── 평균 세션 시간 ───────────────────────────
        durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
        r["avg_session_min"] = round(sum(durations) / len(durations), 1) if durations else 0

        # ── 도구 에러율 ──────────────────────────────
        total_tool_calls = 0
        total_tool_errors = 0
        for s in sessions:
            tools = s.get("tools") or {}
            total_tool_calls += sum(tools.values()) if isinstance(tools, dict) else 0
            errs = s.get("tool_errors") or 0  # session-meta에 tool_errors 필드가 있음
            if isinstance(errs, (int, float)):
                total_tool_errors += errs
        r["tool_error_rate"] = round(
            total_tool_errors / total_tool_calls * 100, 2
        ) if total_tool_calls > 0 else 0

        # ── 사용자 인터럽션 비율 (인터럽션이 1회 이상 발생한 세션 비율) ──
        sessions_with_interrupt = sum(
            1 for s in sessions
            if isinstance(s.get("user_interruptions"), (int, float))
            and s.get("user_interruptions", 0) > 0
        )
        r["interruption_rate"] = round(
            sessions_with_interrupt / len(sessions) * 100, 1
        ) if sessions else 0

        # ── 리스크 판정 (데이터 충분할 때만) ─────────
        if r["confidence"] == "insufficient":
            r["risk_level"] = "low"
            r["concerns"].append("데이터 부족 (세션 5개 미만)")
            return r

        risk = "low"
        # 토큰 트렌드 50% 이상 급증 → medium, 100% 이상 → high
        if r["token_trend_pct"] > 100:
            risk = self._raise_risk(risk, "high")
            r["concerns"].append(f"토큰 증가 {r['token_trend_pct']}%")
        elif r["token_trend_pct"] > 50:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"토큰 증가 {r['token_trend_pct']}%")

        # 도구 에러율 10% 이상 → high, 5% 이상 → medium
        if r["tool_error_rate"] > 10:
            risk = self._raise_risk(risk, "high")
            r["concerns"].append(f"도구 에러율 {r['tool_error_rate']}%")
        elif r["tool_error_rate"] > 5:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"도구 에러율 {r['tool_error_rate']}%")

        # 평균 세션 시간 120분 초과 → medium (컨텍스트 오버플로우 위험)
        if r["avg_session_min"] > 120:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"평균 세션 {r['avg_session_min']}분")

        r["risk_level"] = risk
        return r

    def _perf_mcp_ops(self):
        """MCP 운영 지표 — ops_metrics.db 전체 소스(wiki+jira+gdi) 통합.

        측정 항목:
        - p99_latency_ms: 전체 소스 통합 p99 (elapsed_ms > 0만)
        - error_rate: 전체 응답 대비 실패율(%)
        - cache_hit_rate: 캐시 적중률(%)
        - by_source: 소스별 개별 통계
        """
        r = {"risk_level": "low", "concerns": [], "p99_latency_ms": 0,
             "error_rate": 0, "cache_hit_rate": 0, "by_source": {},
             "total_requests": 0, "details": {}}

        if not os.path.exists(_OPS_DB):
            r["risk_level"] = "unknown"
            r["details"]["db_error"] = "ops_metrics.db 없음"
            return r

        conn = None
        try:
            conn = sqlite3.connect(_OPS_DB, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            # ── 전체 소스 통합 p99 (elapsed_ms > 0만) ─────────
            rows = conn.execute(
                "SELECT elapsed_ms FROM response_events "
                "WHERE date_key >= ? AND elapsed_ms > 0 "
                "ORDER BY elapsed_ms ASC",
                (week_ago,)
            ).fetchall()
            if rows:
                p99_idx = min(int(len(rows) * 0.99), len(rows) - 1)
                r["p99_latency_ms"] = rows[p99_idx]["elapsed_ms"]

            # ── 전체 에러율 ───────────────────────────────────
            total_resp = conn.execute(
                "SELECT COUNT(*) as cnt FROM response_events WHERE date_key >= ?",
                (week_ago,)
            ).fetchone()
            errors = conn.execute(
                "SELECT COUNT(*) as cnt FROM response_events "
                "WHERE date_key >= ? AND result IN ('fail','partial')",
                (week_ago,)
            ).fetchone()
            total_n = total_resp["cnt"] if total_resp else 0
            error_n = errors["cnt"] if errors else 0
            r["total_requests"] = total_n
            r["error_rate"] = round(error_n / total_n * 100, 2) if total_n else 0

            # ── 소스별 개별 통계 ──────────────────────────────
            source_rows = conn.execute(
                "SELECT source, COUNT(*) as cnt, "
                "AVG(CASE WHEN elapsed_ms > 0 THEN elapsed_ms END) as avg_ms, "
                "SUM(CASE WHEN result IN ('fail','partial') THEN 1 ELSE 0 END) as errs "
                "FROM response_events WHERE date_key >= ? GROUP BY source",
                (week_ago,)
            ).fetchall()
            for sr in source_rows:
                src = sr["source"]
                cnt = sr["cnt"]
                avg = round(sr["avg_ms"]) if sr["avg_ms"] else 0
                errs = sr["errs"] or 0
                r["by_source"][src] = {
                    "count": cnt,
                    "avg_latency_ms": avg,
                    "error_rate": round(errs / cnt * 100, 1) if cnt else 0,
                }

            # ── 캐시 적중률 ───────────────────────────────────
            cache_rows = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM cache_events "
                "WHERE date_key >= ? GROUP BY event_type",
                (week_ago,)
            ).fetchall()
            cache_stats = {cr["event_type"]: cr["cnt"] for cr in cache_rows}
            cache_total = sum(cache_stats.values())
            r["cache_hit_rate"] = round(
                cache_stats.get("hit", 0) / cache_total * 100, 1
            ) if cache_total else 0
        except Exception as e:
            r["details"]["db_error"] = str(e)[:80]
        finally:
            if conn:
                conn.close()

        # ── MCP 리스크 판정 ───────────────────────────────
        risk = "low"
        if r["p99_latency_ms"] > 10000:
            risk = self._raise_risk(risk, "high")
            r["concerns"].append(f"p99={r['p99_latency_ms']}ms")
        elif r["p99_latency_ms"] > 3000:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"p99={r['p99_latency_ms']}ms")

        if r["error_rate"] > 10:
            risk = self._raise_risk(risk, "high")
            r["concerns"].append(f"에러율={r['error_rate']}%")
        elif r["error_rate"] > 3:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"에러율={r['error_rate']}%")

        if 0 < r["cache_hit_rate"] < 50:
            risk = self._raise_risk(risk, "medium")
            r["concerns"].append(f"캐시={r['cache_hit_rate']}%")

        r["risk_level"] = risk
        return r

    # ── Claude: 빌더 — Cost & Budget ──────────────────────────
    @staticmethod
    def _build_cost_budget(bot_tokens, cc_data, cfg):
        """사전 파싱된 데이터로 비용 계산. 파일 I/O 없음."""
        import calendar as _cal
        pricing = cfg.get("model_pricing", {})
        haiku_in = pricing.get("haiku", {}).get("input_per_m", 1.0)
        haiku_out = pricing.get("haiku", {}).get("output_per_m", 5.0)
        budget = cfg.get("monthly_limit_usd", 50)
        warn_th = cfg.get("warn_threshold", 0.7)
        crit_th = cfg.get("critical_threshold", 0.9)

        # Bot 비용 (Haiku 기준)
        bot_month_cost = (bot_tokens["month"]["input"] / 1_000_000 * haiku_in +
                          bot_tokens["month"]["output"] / 1_000_000 * haiku_out)
        bot_today_cost = (bot_tokens["today"]["input"] / 1_000_000 * haiku_in +
                          bot_tokens["today"]["output"] / 1_000_000 * haiku_out)

        # CC 비용 (모델별 단가 적용)
        cc_month_cost = 0.0
        cc_today_cost = 0.0
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        today_str = now.strftime("%Y-%m-%d")

        for sess in cc_data["sessions"]:
            in_tok = sess["input_tokens"]
            out_tok = sess["output_tokens"]
            model_raw = (sess["model"] or "haiku").lower()

            if "opus" in model_raw:
                m_in = pricing.get("opus", {}).get("input_per_m", 15.0)
                m_out = pricing.get("opus", {}).get("output_per_m", 75.0)
            elif "sonnet" in model_raw:
                m_in = pricing.get("sonnet", {}).get("input_per_m", 3.0)
                m_out = pricing.get("sonnet", {}).get("output_per_m", 15.0)
            else:
                m_in = haiku_in
                m_out = haiku_out

            cost = in_tok / 1_000_000 * m_in + out_tok / 1_000_000 * m_out
            sd = sess["date"] or ""
            if sd.startswith(month_str):
                cc_month_cost += cost
            if sd == today_str:
                cc_today_cost += cost

        total_month = round(bot_month_cost + cc_month_cost, 2)
        total_today = round(bot_today_cost + cc_today_cost, 2)
        usage_pct = round(total_month / budget, 3) if budget > 0 else 0

        if usage_pct >= crit_th:
            alert = "critical"
        elif usage_pct >= warn_th:
            alert = "warning"
        else:
            alert = "normal"

        day_of_month = now.day
        daily_avg = total_month / day_of_month
        days_in_month = _cal.monthrange(now.year, now.month)[1]
        projected = round(daily_avg * days_in_month, 2)

        return {
            "today_usd": total_today,
            "month_usd": total_month,
            "budget_usd": budget,
            "usage_pct": usage_pct,
            "projected_month_usd": projected,
            "remaining_usd": round(budget - total_month, 2),
            "alert_level": alert,
            "breakdown": {
                "bot_month": round(bot_month_cost, 2),
                "cc_month": round(cc_month_cost, 2),
                "bot_today": round(bot_today_cost, 2),
                "cc_today": round(cc_today_cost, 2),
            },
            "disclaimer": "로컬 커맨드 기준 추정치 (Railway 제외)",
        }

    # ── Claude: Config 로드 ───────────────────────────────────
    @staticmethod
    def _load_claude_config():
        """claude_config.json 로드. 없으면 기본값."""
        try:
            with open(_CLAUDE_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "monthly_limit_usd": 50,
                "warn_threshold": 0.7,
                "critical_threshold": 0.9,
                "model_pricing": {
                    "haiku": {"input_per_m": 1.0, "output_per_m": 5.0},
                    "sonnet": {"input_per_m": 3.0, "output_per_m": 15.0},
                    "opus": {"input_per_m": 15.0, "output_per_m": 75.0},
                },
                "refresh_interval_sec": 300,
                "session_meta_max_days": 90,
                "mcp_ping_timeout_sec": 3,
            }

    def _ops_cache_efficiency(self):
        """캐시 히트/미스/폴백 비율."""
        if not os.path.exists(_OPS_DB):
            return {"overall": {"hit": 0, "miss": 0, "fallback": 0,
                                "total": 0, "hit_rate": 0},
                    "by_source": {}, "period_days": 7}
        try:
            conn = sqlite3.connect(_OPS_DB, timeout=5)
            conn.row_factory = sqlite3.Row
            date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT source, event_type, COUNT(*) as cnt "
                "FROM cache_events WHERE date_key >= ? "
                "GROUP BY source, event_type", (date_from,)
            ).fetchall()
            conn.close()

            by_source = {}
            overall = {"hit": 0, "miss": 0, "fallback": 0}
            for r in rows:
                src = r["source"]
                if src not in by_source:
                    by_source[src] = {"hit": 0, "miss": 0, "fallback": 0}
                by_source[src][r["event_type"]] = r["cnt"]
                overall[r["event_type"]] = overall.get(r["event_type"], 0) + r["cnt"]

            for d in [overall] + list(by_source.values()):
                total = d.get("hit", 0) + d.get("miss", 0) + d.get("fallback", 0)
                d["total"] = total
                d["hit_rate"] = round(d["hit"] / total * 100, 1) if total else 0
            return {"overall": overall, "by_source": by_source, "period_days": 7}
        except Exception as e:
            return {"error": str(e)}

    def _ops_response_summary(self):
        """답변 성공/실패 요약."""
        if not os.path.exists(_OPS_DB):
            return {"overall": {"success": 0, "fail": 0, "partial": 0,
                                "total": 0, "fail_rate": 0},
                    "by_source": {}, "avg_elapsed_ms": {}}
        try:
            conn = sqlite3.connect(_OPS_DB, timeout=5)
            conn.row_factory = sqlite3.Row
            date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            rows = conn.execute(
                "SELECT source, result, COUNT(*) as cnt "
                "FROM response_events WHERE date_key >= ? "
                "GROUP BY source, result", (date_from,)
            ).fetchall()

            by_source = {}
            overall = {"success": 0, "fail": 0, "partial": 0}
            for r in rows:
                src = r["source"]
                if src not in by_source:
                    by_source[src] = {"success": 0, "fail": 0, "partial": 0}
                by_source[src][r["result"]] = r["cnt"]
                overall[r["result"]] = overall.get(r["result"], 0) + r["cnt"]

            for d in [overall] + list(by_source.values()):
                total = d.get("success", 0) + d.get("fail", 0) + d.get("partial", 0)
                d["total"] = total
                d["fail_rate"] = round(d["fail"] / total * 100, 1) if total else 0

            elapsed_rows = conn.execute(
                "SELECT source, AVG(elapsed_ms) as avg_ms "
                "FROM response_events WHERE date_key >= ? AND elapsed_ms > 0 "
                "GROUP BY source", (date_from,)
            ).fetchall()
            avg_elapsed = {r["source"]: round(r["avg_ms"]) for r in elapsed_rows}
            conn.close()

            return {"overall": overall, "by_source": by_source,
                    "avg_elapsed_ms": avg_elapsed}
        except Exception as e:
            return {"error": str(e)}

    def _ops_daily_trend(self):
        """일별 캐시/응답 트렌드 (최근 7일)."""
        if not os.path.exists(_OPS_DB):
            return []
        try:
            conn = sqlite3.connect(_OPS_DB, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT date_key, source, metric, count FROM daily_stats "
                "WHERE date_key >= date('now', '-7 days') "
                "ORDER BY date_key DESC, source"
            ).fetchall()
            conn.close()

            pivot = {}
            for r in rows:
                key = (r["date_key"], r["source"])
                if key not in pivot:
                    pivot[key] = {"date_key": r["date_key"], "source": r["source"]}
                pivot[key][r["metric"]] = r["count"]
            return list(pivot.values())
        except Exception as e:
            return [{"error": str(e)}]

    def _ops_recent_failures(self):
        """최근 답변 실패 내역 (최대 20건)."""
        if not os.path.exists(_OPS_DB):
            return []
        try:
            conn = sqlite3.connect(_OPS_DB, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ts, source, query, result, fail_reason, "
                "page_title, elapsed_ms, user_id "
                "FROM response_events "
                "WHERE result IN ('fail', 'partial') "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            return [{"error": str(e)}]

    def _ops_design_check(self):
        """시스템 설계 정합성 검증."""
        checks = []

        # 1. 캐시 레이어 존재 확인
        cache_exists = os.path.exists(_CACHE_DB)
        checks.append({
            "name": "캐시 DB 존재",
            "status": "ok" if cache_exists else "fail",
            "detail": _CACHE_DB if cache_exists else "파일 없음",
        })

        # 2. ops_metrics DB 존재
        ops_exists = os.path.exists(_OPS_DB)
        checks.append({
            "name": "운영지표 DB 존재",
            "status": "ok" if ops_exists else "warn",
            "detail": "정상" if ops_exists else "아직 데이터 없음 (봇 재시작 필요)",
        })

        # 3. 캐시 적재율 (노드 수)
        if cache_exists:
            try:
                conn = sqlite3.connect(_CACHE_DB, timeout=5)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT source_type, COUNT(*) as cnt FROM nodes "
                    "GROUP BY source_type"
                ).fetchall()
                node_counts = {r["source_type"]: r["cnt"] for r in rows}
                conn.close()

                for src, expected_min in [("wiki", 2500), ("jira", 5000), ("gdi", 10000)]:
                    cnt = node_counts.get(src, 0)
                    status = "ok" if cnt >= expected_min else "warn"
                    checks.append({
                        "name": f"{src.upper()} 노드 수",
                        "status": status,
                        "detail": f"{cnt:,}개 (최소 {expected_min:,} 권장)",
                    })
            except Exception as e:
                checks.append({"name": "캐시 노드 수", "status": "fail",
                               "detail": str(e)})

        # 4. enrichment 비율
        if cache_exists:
            try:
                conn = sqlite3.connect(_CACHE_DB, timeout=5)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT n.source_type, "
                    "COUNT(*) as total, "
                    "SUM(CASE WHEN dc.summary IS NOT NULL AND dc.summary != '' THEN 1 ELSE 0 END) as enriched "
                    "FROM nodes n LEFT JOIN doc_content dc ON dc.node_id = n.id "
                    "GROUP BY n.source_type"
                ).fetchall()
                conn.close()
                for r in rows:
                    total = r["total"]
                    enriched = r["enriched"] or 0
                    rate = round(enriched / total * 100, 1) if total else 0
                    status = "ok" if rate >= 80 else ("warn" if rate >= 50 else "fail")
                    checks.append({
                        "name": f"{r['source_type'].upper()} Enrichment",
                        "status": status,
                        "detail": f"{enriched:,}/{total:,} ({rate}%)",
                    })
            except Exception:
                pass

        # 5. 최근 캐시 히트율 (ops_metrics)
        if ops_exists:
            try:
                conn = sqlite3.connect(_OPS_DB, timeout=5)
                conn.row_factory = sqlite3.Row
                date_from = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                rows = conn.execute(
                    "SELECT event_type, COUNT(*) as cnt "
                    "FROM cache_events WHERE date_key >= ? "
                    "GROUP BY event_type", (date_from,)
                ).fetchall()
                conn.close()
                counts = {r["event_type"]: r["cnt"] for r in rows}
                hit = counts.get("hit", 0)
                total = hit + counts.get("miss", 0) + counts.get("fallback", 0)
                if total > 0:
                    rate = round(hit / total * 100, 1)
                    status = "ok" if rate >= 60 else ("warn" if rate >= 30 else "fail")
                    checks.append({
                        "name": "24h 캐시 히트율",
                        "status": status,
                        "detail": f"{rate}% ({hit}/{total})",
                    })
            except Exception:
                pass

        return checks

    def log_message(self, format, *args):
        # Quieter logging — API 요청만 출력
        first = str(args[0]) if args else ""
        if "/api/" in first:
            sys.stderr.write(f"[proxy] {first}\n")


def _fix_pythonw_stdio():
    """pythonw.exe 환경에서 stdout/stderr가 None일 때 파일로 리다이렉트.

    pythonw.exe는 콘솔이 없어 sys.stdout/stderr가 None이 됨.
    http.server의 log_request()가 stderr.write()를 호출하면 크래시 →
    TCP 연결은 맺히지만 빈 응답(Empty reply) 반환하는 문제 발생.
    """
    log_dir = os.path.join(os.path.dirname(STATIC_DIR), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "s3_server.log")

    if sys.stdout is None:
        sys.stdout = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(log_path, "a", encoding="utf-8", buffering=1)


def main():
    _fix_pythonw_stdio()

    parser = argparse.ArgumentParser(description="GDI S3 File Manager")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--silent", action="store_true", help="브라우저 자동 열기 비활성화")
    args = parser.parse_args()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), ProxyHandler)
    print(f"GDI S3 File Manager → http://localhost:{args.port}/s3_manager.html")
    print(f"GDI API proxy       → http://localhost:{args.port}/api/*")

    if not args.silent:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}/s3_manager.html")
    else:
        print("Silent mode — browser not opened")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
