"""Serve tests/fixture/ like the real API, for offline testing.

    python tests/fake_api.py 8765 &
    GRUBER_API=http://127.0.0.1:8765/Hackaton2026 python fetch.py
Files are re-read on every request, so re-running make_fixture.py simulates an API change.
"""
import re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIX = Path(__file__).parent / "fixture"
ROUTES = [
    (r"/Hackaton2026/Scenarios", lambda m: FIX / "Scenarios.json"),
    (r"/Hackaton2026/Scenarios/([^/]+)/Cities", lambda m: FIX / m[1] / "Cities.json"),
    (r"/Hackaton2026/Scenarios/([^/]+)/Trucks", lambda m: FIX / m[1] / "Trucks.json"),
    (r"/Hackaton2026/Scenarios/([^/]+)/Orders", lambda m: FIX / m[1] / "Orders.json"),
    (r"/Hackaton2026/Scenarios/([^/]+)/DistanceMatrix/csv", lambda m: FIX / m[1] / "DistanceMatrix.csv"),
]


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        for pat, f in ROUTES:
            m = re.fullmatch(pat, self.path.split("?")[0])
            if m and f(m).exists():
                body = f(m).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv" if self.path.endswith("csv") else "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
        self.send_error(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H).serve_forever()
