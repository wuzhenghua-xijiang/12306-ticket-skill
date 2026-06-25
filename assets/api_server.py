#!/usr/bin/env python3
"""12306 API Server — 本地HTTP服务，供前端页面调用"""
import sys, os, json, urllib.parse, re
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import query12306 as q

q.load_stations()

HOST, PORT = "127.0.0.1", 8765

class Handler(BaseHTTPRequestHandler):
    def _cors(self, status=200, ct="application/json"):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", f"{ct}; charset=utf-8")
        self.end_headers()

    def do_OPTIONS(self):
        self._cors(204, "text/plain")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/query":
            self._cors(404, "text/plain")
            self.wfile.write(b"Not found. Use /api/query?from=...&to=...&date=...&hubs=...")
            return

        params = urllib.parse.parse_qs(parsed.query)
        from_s = params.get("from", [""])[0]
        to_s = params.get("to", [""])[0]
        date = params.get("date", [""])[0]
        hubs = params.get("hubs", [""])[0]

        if not from_s or not to_s or not date:
            self._cors(400)
            self.wfile.write(json.dumps({"error": "缺少参数 from/to/date"}, ensure_ascii=False).encode())
            return

        hubs_list = [h.strip() for h in hubs.split(",") if h.strip()] if hubs else None

        print(f"[API] {date} {from_s}→{to_s} hubs={hubs_list or 'auto'}", flush=True)

        # 直达
        d_direct = q.query_tickets(date, from_s, to_s)
        if 'error' in d_direct:
            d_direct_out = None
            q._init_session(force=True)
        else:
            d_direct_out = {"count": d_direct["count"], "trains": d_direct["trains"]}

        # 中转
        d_transfer = q.search_transfers(date, from_s, to_s,
            min_gap=20, max_gap=1440, max_results=99999, hubs=hubs_list)
        t_out = {
            "checked_hubs": d_transfer.get("checked_hubs", 0),
            "found": d_transfer.get("found", 0),
            "transfers": d_transfer.get("transfers", []),
        }

        result = {"from": d_transfer.get("from", from_s), "to": d_transfer.get("to", to_s),
                  "date": date, "direct": d_direct_out, "transfers": t_out}
        self._cors()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        print(f"[API] done: 直达{len(d_direct_out['trains']) if d_direct_out else 0}趟, 中转{t_out['found']}方案", flush=True)

    def log_message(self, fmt, *args):
        pass  # silence default logs

if __name__ == "__main__":
    print(f"🚄 12306 API Server → http://{HOST}:{PORT}/api/query?from=杭州&to=兰考&date=2026-06-28&hubs=徐州,商丘")
    HTTPServer((HOST, PORT), Handler).serve_forever()
