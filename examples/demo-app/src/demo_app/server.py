import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from demo_app.pricing import price_with_vat

HOST = "127.0.0.1"
PORT = 8765


class PriceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        net = int(self.path.strip("/") or 0)
        body = json.dumps({"net": net, "gross": price_with_vat(net)})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


def main() -> None:
    HTTPServer((HOST, PORT), PriceHandler).serve_forever()


if __name__ == "__main__":
    main()
