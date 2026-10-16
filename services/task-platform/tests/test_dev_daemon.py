import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_wait_http_requires_2xx_and_keeps_nohup_fallback(tmp_path):
    source = (ROOT / "ops" / "dev" / "daemon.sh").read_text(encoding="utf-8")
    assert "setsid nohup" in source
    assert 'nohup "$@"' in source
    helper = tmp_path / "probe.py"
    helper.write_text(
        textwrap.dedent(
            """
            import sys
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            from pathlib import Path

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/health":
                        code = 200 if self.headers.get("X-User-ID") == "nexus" else 401
                    elif self.path == "/bad":
                        code = 500
                    else:
                        code = 422
                    self.send_response(code)
                    self.end_headers()

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            Path(sys.argv[1]).write_text(str(server.server_address[1]), encoding="utf-8")
            server.serve_forever()
            """
        ),
        encoding="utf-8",
    )
    script = tmp_path / "check.sh"
    script.write_text(
        textwrap.dedent(
            f"""
            set -euo pipefail
            LOG={tmp_path / "daemon.log"}
            . "{ROOT / "ops" / "dev" / "daemon.sh"}"
            portfile="{tmp_path / "port"}"
            start_probe() {{
              python3 "{helper}" "$portfile" >/dev/null 2>&1 &
              echo "$!"
            }}
            pid="$(start_probe)"
            for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
              if [ -s "$portfile" ]; then
                break
              fi
              sleep 0.05
            done
            port="$(cat "$portfile")"
            rm -f "$portfile"
            set +e
            wait_http "http://127.0.0.1:${{port}}/bad" "$pid" 2
            bad=$?
            set -e
            if [ "$bad" -eq 0 ]; then
              echo "500 was treated as ready" >&2
              exit 1
            fi
            pid="$(start_probe)"
            for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
              if [ -s "$portfile" ]; then
                break
              fi
              sleep 0.05
            done
            port="$(cat "$portfile")"
            rm -f "$portfile"
            set +e
            wait_http "http://127.0.0.1:${{port}}/health" "$pid" 2
            missing=$?
            set -e
            if [ "$missing" -eq 0 ]; then
              echo "401 was treated as ready" >&2
              exit 1
            fi
            pid="$(start_probe)"
            for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
              if [ -s "$portfile" ]; then
                break
              fi
              sleep 0.05
            done
            port="$(cat "$portfile")"
            if ! wait_http "http://127.0.0.1:${{port}}/health" "$pid" 5 -H "X-User-ID: nexus"; then
              echo "200 with X-User-ID was not ready" >&2
              kill "$pid" 2>/dev/null || true
              exit 1
            fi
            kill -0 "$pid"
            kill "$pid"
            wait "$pid" 2>/dev/null || true
            """
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
