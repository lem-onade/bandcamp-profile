"""A local stand-in for the parts of Bandcamp that bandcamp-sync talks to.

Responses mirror the shapes of saved Bandcamp answers (see tests/samples/).
Run it on its own for a manual try: python tests/fake_bandcamp.py --port 8765
"""

from __future__ import annotations

import html
import io
import json
import threading
import zipfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SAMPLES = Path(__file__).parent / "samples"
GOOD_COOKIE = "7%09abcDEF%3D%3D%09%7B%22id%22%3A1%7D"
FAN_ID = 3950257


def album_zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            z.writestr(name, f"audio of {name}".encode())
    return buf.getvalue()


@dataclass
class FakeItem:
    sale_item_id: int
    artist: str
    title: str
    type: str = "album"  # album | track
    sale_item_type: str = "p"
    hidden: bool = False
    downloadable: bool = True
    formats: tuple[str, ...] = ("flac", "mp3-320", "mp3-v0")
    fail: str | None = None  # "file" -> 500 on the file, "zip" -> corrupt zip
    not_ready: int = 0  # statdownload answers "err" this many times first

    @property
    def item_id(self) -> int:
        return self.sale_item_id + 5000

    @property
    def key(self) -> str:
        return f"{self.sale_item_type}{self.sale_item_id}"


@dataclass
class FakeBandcamp:
    items: list[FakeItem]
    page_size: int = 1
    summary_has_fan_id: bool = True
    requests: list[str] = field(default_factory=list)
    base_url: str = ""

    def item(self, sale_item_id: int) -> FakeItem:
        return next(i for i in self.items if i.sale_item_id == sale_item_id)


def _item_json(item: FakeItem, index: int) -> dict:
    sample = json.loads((SAMPLES / "collection_item.json").read_text())
    sample.update(
        band_name=item.artist,
        item_title=item.title,
        item_id=item.item_id,
        tralbum_id=item.item_id,
        tralbum_type="a" if item.type == "album" else "t",
        item_type=item.type,
        sale_item_type=item.sale_item_type,
        sale_item_id=item.sale_item_id,
        token=f"{1700000000 - index}:{item.item_id}:a::",
    )
    return sample


def make_handler(fake: FakeBandcamp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200):
            self._send(status, json.dumps(data).encode(), "application/json")

        def _logged_in(self) -> bool:
            return f"identity={GOOD_COOKIE}" in (self.headers.get("Cookie") or "")

        def do_GET(self):
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            fake.requests.append(f"GET {url.path}")

            if url.path == "/api/fan/2/collection_summary":
                if not self._logged_in():
                    return self._json({"error": True, "error_message": "not logged in"})
                summary = {"username": "lmnd", "url": f"{fake.base_url}/lmnd", "tralbum_lookup": {}}
                if fake.summary_has_fan_id:
                    return self._json({"fan_id": FAN_ID, "collection_summary": {"fan_id": FAN_ID, **summary}})
                return self._json({"collection_summary": summary})

            if url.path == "/lmnd":
                blob = html.escape(json.dumps({"fan_data": {"fan_id": FAN_ID, "username": "lmnd"}}))
                return self._send(200, f'<html><div id="pagedata" data-blob="{blob}"></div></html>'.encode(), "text/html")

            if url.path == "/download" and "sitem_id" in query:
                if not self._logged_in():
                    return self._send(403, b"forbidden", "text/plain")
                item = fake.item(int(query["sitem_id"]))
                blob = json.loads((SAMPLES / "redownload_pagedata.json").read_text())
                kind = "album" if item.type == "album" else "track"
                downloads = {
                    fmt: {
                        "size_mb": "10MB",
                        "description": fmt,
                        "encoding_name": fmt,
                        "url": f"{fake.base_url}/download/{kind}?enc={fmt}&fsig=abc&id={item.item_id}&ts=1700000000.0",
                    }
                    for fmt in item.formats
                }
                digital = blob["digital_items"][0]
                digital.update(title=item.title, artist=item.artist, type=item.type, downloads=downloads)
                page = (
                    '<!DOCTYPE html><html><body><div id="pagedata" '
                    f'data-blob="{html.escape(json.dumps(blob))}"></div></body></html>'
                )
                return self._send(200, page.encode(), "text/html; charset=utf-8")

            if url.path.startswith("/statdownload/"):
                item = next(i for i in fake.items if i.item_id == int(query["id"]))
                if item.not_ready > 0:
                    item.not_ready -= 1
                    result = {"result": "err", "retry_url": f"{fake.base_url}{self.path}"}
                else:
                    result = {
                        "result": "ok",
                        "download_url": f"{fake.base_url}/files/{item.item_id}?enc={query.get('enc')}",
                    }
                body = f"if ( window.Downloads ) {{ Downloads.statResult ( {json.dumps(result)} ) }};"
                return self._send(200, body.encode(), "text/javascript")

            if url.path.startswith("/files/"):
                item = next(i for i in fake.items if i.item_id == int(url.path.rsplit("/", 1)[1]))
                if item.fail == "file":
                    return self._send(500, b"server error", "text/plain")
                if item.type == "album":
                    body = album_zip([f"{item.artist} - {item.title} - 0{n} Song {n}.flac" for n in (1, 2)] + ["cover.jpg"])
                    if item.fail == "zip":
                        body = b"PK\x03\x04" + body[4:200]
                    name = f"{item.artist} - {item.title}.zip"
                else:
                    body = f"audio of {item.title}".encode()
                    name = f"{item.artist} - {item.title}.flac"
                return self._send(200, body, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{name}"'})

            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            url = urlsplit(self.path)
            fake.requests.append(f"POST {url.path}")
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            endpoint = url.path.rsplit("/", 1)[-1]
            if endpoint not in ("collection_items", "hidden_items"):
                return self._send(404, b"not found", "text/plain")
            if body.get("fan_id") != FAN_ID:
                return self._json({"error": True, "error_message": "bad fan_id"})

            hidden = endpoint == "hidden_items"
            pool = [(n, i) for n, i in enumerate(fake.items) if i.hidden == hidden]
            token = body.get("older_than_token", "")
            start = 0
            if token.startswith("page:"):
                start = int(token.split(":")[1])
            page = pool[start : start + fake.page_size]
            more = start + fake.page_size < len(pool)
            self._json(
                {
                    "items": [_item_json(i, n) for n, i in page],
                    "more_available": more,
                    "last_token": f"page:{start + fake.page_size}" if more else None,
                    "redownload_urls": {
                        i.key: f"{fake.base_url}/download?from=collection&payment_id=9{i.sale_item_id}&sig=s&sitem_id={i.sale_item_id}"
                        for _, i in page
                        if i.downloadable
                    },
                    "item_lookup": {},
                    "tracklists": {},
                }
            )

    return Handler


def serve(fake: FakeBandcamp, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(fake))
    fake.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def demo_items() -> list[FakeItem]:
    return [
        FakeItem(1001, "Ana Roxanne", "Because of a Flower", type="album"),
        FakeItem(1002, "Khruangbin", "Pelota", type="track"),
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = serve(FakeBandcamp(demo_items()), args.port)
    print(f"fake Bandcamp on http://127.0.0.1:{args.port} (cookie: {GOOD_COOKIE})", flush=True)
    threading.Event().wait()
