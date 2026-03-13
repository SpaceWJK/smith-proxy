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

GDI_API = (
    "http://k8s-llmopsalbgroup-2f93202457-431440703"
    ".ap-northeast-1.elb.amazonaws.com/game-doc-insight-ui/api"
)
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Dashboard 데이터 소스 경로 ─────────────────────────────────
_PROJECT_ROOT = os.path.normpath(os.path.join(STATIC_DIR, ".."))
_BOT_SRC = os.path.join(_PROJECT_ROOT, "Slack Bot")
_BOT_DATA = os.path.join(_BOT_SRC, "data")
_LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")
_CACHE_DB = os.path.normpath(
    os.path.join(_PROJECT_ROOT, "..", "QA Ops", "mcp-cache-layer", "cache", "mcp_cache.db")
)


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server + GDI API reverse proxy."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    # ── API proxy ───────────────────────────────────────────
    def do_GET(self):
        if self.path == "/api/dashboard":
            self._handle_dashboard()
        elif self.path.startswith("/api/"):
            self._proxy_get()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy_post()
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

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
            import subprocess
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command',
                 "Get-CimInstance Win32_Process -Filter"
                 " \"name='python.exe' or name='pythonw.exe'\" |"
                 " Select-Object -ExpandProperty CommandLine"],
                text=True, timeout=10,
            )
            bot_running = "slack_bot" in out.lower()
        except Exception:
            bot_running = False

        # 최근 sync 기록 (SQLite)
        last_sync = None
        try:
            conn = sqlite3.connect(f"file:{_CACHE_DB}?mode=ro", uri=True, timeout=3)
            cur = conn.cursor()
            cur.execute(
                "SELECT source_type, started_at, status, duration_sec "
                "FROM sync_log ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                last_sync = {
                    "source": row[0],
                    "time": row[1],
                    "status": row[2],
                    "duration": row[3],
                }
            conn.close()
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

    def _dash_processes(self):
        """관련 Python 프로세스 목록 반환 (조회만, Kill 불가)."""
        procs = []
        try:
            import subprocess
            # PowerShell로 python/pythonw 프로세스 정보 수집
            # CreationDate를 문자열로 변환하여 반환
            ps_cmd = (
                "Get-CimInstance Win32_Process "
                "-Filter \"name='python.exe' or name='pythonw.exe'\" "
                "| Select-Object ProcessId, Name, "
                "@{N='MemMB';E={[math]::Round($_.WorkingSetSize/1MB,1)}}, "
                "CommandLine, "
                "@{N='Created';E={$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss')}} "
                "| ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                text=True, timeout=10,
            ).strip()
            if not out:
                return {"processes": [], "warnings": []}

            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]

            # 프로세스 분류
            seen_types = {}  # type -> count
            for p in data:
                cmd = (p.get("CommandLine") or "").lower()
                pid = p.get("ProcessId", 0)
                mem_mb = p.get("MemMB", 0)
                name = p.get("Name", "")

                # 프로세스 유형 식별
                if "slack_bot" in cmd:
                    ptype = "slack_bot"
                    label = "Slack Bot"
                elif "s3_server" in cmd:
                    ptype = "s3_server"
                    label = "KIS Server"
                elif "auto_sync" in cmd:
                    ptype = "auto_sync"
                    label = "Auto Sync"
                elif "enrichment" in cmd:
                    ptype = "enrichment"
                    label = "Enrichment"
                else:
                    ptype = "other_python"
                    label = "Python"

                # 커맨드라인 미리보기 — 민감 정보 마스킹
                raw_cmd = (p.get("CommandLine") or "")[:120]
                safe_cmd = self._SENSITIVE_RE.sub(r'\1****', raw_cmd)

                seen_types[ptype] = seen_types.get(ptype, 0) + 1
                procs.append({
                    "pid": pid,
                    "name": name,
                    "type": ptype,
                    "label": label,
                    "mem_mb": mem_mb,
                    "created": p.get("Created", ""),
                    "cmd_preview": safe_cmd,
                })

            # 경고 생성: 중복 프로세스 탐지
            warnings = []
            for ptype, count in seen_types.items():
                if ptype in ("slack_bot", "s3_server") and count > 1:
                    label = "Slack Bot" if ptype == "slack_bot" else "KIS Server"
                    warnings.append(
                        f"⚠️ {label} 중복 실행 감지 ({count}개) — 수동 확인 필요"
                    )
            return {"processes": procs, "warnings": warnings}

        except Exception as e:
            return {"processes": [], "warnings": [f"프로세스 조회 실패: {str(e)}"]}

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

    def log_message(self, format, *args):
        # Quieter logging
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"[proxy] {args[0]}\n")


def main():
    parser = argparse.ArgumentParser(description="GDI S3 File Manager")
    parser.add_argument("--port", type=int, default=9090)
    args = parser.parse_args()

    server = http.server.HTTPServer(("0.0.0.0", args.port), ProxyHandler)
    print(f"GDI S3 File Manager → http://localhost:{args.port}/s3_manager.html")
    print(f"GDI API proxy       → http://localhost:{args.port}/api/*")
    print("Press Ctrl+C to stop")

    import webbrowser
    webbrowser.open(f"http://localhost:{args.port}/s3_manager.html")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
