#!/usr/bin/env python3
"""
Local test server: serves the files of the current folder and forwards /iiif/... to Digilib,
adding the CORS header that the Hertziana server does not send.
For local testing only.

Digilib currently answers info.json with 200 and an empty body, while regions and tiles
work. In that case the proxy builds an info.json with the canvas size found in
manifest.json. If Digilib starts sending it again, the original one is used.

Use (from a folder built with `convert.py --proxy --out DIR`, plus index.html):
  python3 /path/to/serve.py      then open http://localhost:8000/
"""
import http.server
import json
import os
import urllib.error
import urllib.request

PORT = int(os.environ.get("PORT", "8000"))
UPSTREAM = os.environ.get("UPSTREAM", "https://img.biblhertz.it/digilib/Scaler/IIIF/3/")
LOCAL = f"http://localhost:{PORT}/iiif/"
INFO_SUFFIX = "/info.json"


def canvas_size(ident):
    """Size of the canvas in manifest.json that uses the image service `ident`."""
    with open("manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    for canvas in manifest["items"]:
        for page in canvas["items"]:
            for anno in page["items"]:
                for service in anno["body"].get("service", []):
                    if service["id"].rsplit("/", 1)[-1] == ident:
                        return canvas["width"], canvas["height"]
    raise LookupError(f"{ident} is not in manifest.json")


def synthetic_info(ident):
    width, height = canvas_size(ident)
    factors = [1]
    while max(width, height) / factors[-1] > 256:
        factors.append(factors[-1] * 2)
    return json.dumps({
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": LOCAL + ident,
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level2",
        "width": width,
        "height": height,
        "tiles": [{"width": 256, "scaleFactors": factors}],
    }).encode()


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/iiif/"):
            self.proxy()
        else:
            super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/iiif/"):
            self.proxy(send_body=False)
        else:
            super().do_HEAD()

    def proxy(self, send_body=True):
        rest = self.path[len("/iiif/"):]
        is_info = rest.endswith(INFO_SUFFIX)
        try:
            with urllib.request.urlopen(UPSTREAM + rest, timeout=60) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            self.send_error(e.code, f"Digilib: {e.reason}")
            return
        except Exception as e:
            self.send_error(502, f"Digilib not reachable: {e}")
            return

        if is_info and body:
            # the tiles must go through the proxy too
            for scheme in ("http://", "https://"):
                upstream = scheme + UPSTREAM.split("://", 1)[1]
                body = body.replace(upstream.encode(), LOCAL.encode())
        elif is_info:
            try:
                body = synthetic_info(rest[:-len(INFO_SUFFIX)])
            except (OSError, ValueError, KeyError, LookupError) as e:
                self.send_error(502, f"Empty info.json from Digilib and image size not available: {e}")
                return
            ctype = "application/json"
        elif not body:
            self.send_error(502, "Digilib answered with an empty body")
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)


if __name__ == "__main__":
    print(f"Open http://localhost:{PORT}/   (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("", PORT), Handler).serve_forever()
