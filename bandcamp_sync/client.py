"""HTTP access to Bandcamp: login, listing purchases and fetching their files."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import requests

DEFAULT_BASE_URL = "https://bandcamp.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
PAGE_SIZE = 100


class AuthError(Exception):
    """The cookie was rejected or no fan id could be found for it."""


class BandcampError(Exception):
    """Bandcamp answered with something we can't use."""


@dataclass
class Purchase:
    artist: str
    title: str
    type: str  # "album" or "track"
    sale_item_type: str
    sale_item_id: int
    item_id: int
    redownload_url: str | None

    @property
    def sale_key(self) -> str:
        return f"{self.sale_item_type}{self.sale_item_id}"


class _PageDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blob = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.blob is None and attrs.get("id") == "pagedata":
            self.blob = attrs.get("data-blob")


def parse_pagedata(html_text: str) -> dict:
    """Return the JSON in a Bandcamp page's #pagedata data-blob."""
    parser = _PageDataParser()
    parser.feed(html_text)
    if not parser.blob:
        raise BandcampError("page has no #pagedata blob")
    try:
        return json.loads(parser.blob)
    except json.JSONDecodeError as e:
        raise BandcampError(f"page data isn't valid JSON: {e}") from None


def download_formats(blob: dict) -> dict[str, str]:
    """Map each format offered on a redownload page to its download URL."""
    items = blob.get("digital_items") or blob.get("download_items") or []
    if not items:
        raise BandcampError("redownload page lists no digital items")
    downloads = items[0].get("downloads") or {}
    return {fmt: d["url"] for fmt, d in downloads.items() if isinstance(d, dict) and d.get("url")}


def _first_json_object(text: str) -> dict:
    """statdownload answers JSON, sometimes wrapped in a JS callback; take the first object."""
    match = re.search(r'\{\s*"', text)
    if not match:
        raise BandcampError("statdownload answer has no JSON")
    start = match.start()
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise BandcampError(f"statdownload answer isn't valid JSON: {e}") from None
    return obj


def _filename_from_response(response: requests.Response) -> str | None:
    disposition = response.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    if m:
        return m.group(1).strip()
    name = os.path.basename(urlsplit(response.url).path)
    return name or None


class Client:
    def __init__(
        self,
        identity: str,
        base_url: str | None = None,
        log: Callable[[str], None] | None = None,
        stat_retries: int = 5,
        stat_wait: float = 5.0,
    ):
        self.base_url = (base_url or os.environ.get("BANDCAMP_SYNC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._identity = identity
        self._log = log or (lambda msg: None)
        self.stat_retries = stat_retries
        self.stat_wait = stat_wait
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._base_host = urlsplit(self.base_url).hostname

    def _cookie_for(self, url: str) -> dict:
        # Only Bandcamp's own hosts (or the configured base host) get the login cookie.
        host = urlsplit(url).hostname or ""
        if host == self._base_host or host == "bandcamp.com" or host.endswith(".bandcamp.com"):
            return {"Cookie": f"identity={self._identity}"}
        return {}

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._log(f"{method} {url.split('?')[0]}")
        headers = {**kwargs.pop("headers", {}), **self._cookie_for(url)}
        response = self.session.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 60), **kwargs)
        self._log(f"  -> {response.status_code}")
        return response

    # Login

    def fan_id(self) -> int:
        response = self._request("GET", f"{self.base_url}/api/fan/2/collection_summary")
        if response.status_code in (401, 403):
            raise AuthError("Bandcamp rejected the cookie")
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            raise AuthError("Bandcamp didn't return a collection summary for this cookie") from None
        summary = data.get("collection_summary") or {}
        fan_id = data.get("fan_id") or summary.get("fan_id")
        if fan_id:
            return int(fan_id)
        username = summary.get("username")
        if username:
            page = self._request("GET", f"{self.base_url}/{username}")
            page.raise_for_status()
            fan_id = (parse_pagedata(page.text).get("fan_data") or {}).get("fan_id")
            if fan_id:
                return int(fan_id)
        raise AuthError("Bandcamp rejected the cookie (no fan id for this session)")

    # Listing purchases

    def _page_items(self, endpoint: str, fan_id: int) -> tuple[list[dict], dict[str, str]]:
        items: list[dict] = []
        urls: dict[str, str] = {}
        token = f"{int(time.time())}::a::"
        while True:
            response = self._request(
                "POST",
                f"{self.base_url}/api/fancollection/1/{endpoint}",
                json={"fan_id": fan_id, "older_than_token": token, "count": PAGE_SIZE},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("error"):
                raise BandcampError(f"{endpoint}: {data.get('error_message') or 'error'}")
            items.extend(data.get("items") or [])
            urls.update(data.get("redownload_urls") or {})
            if not data.get("more_available") or not data.get("last_token"):
                return items, urls
            token = data["last_token"]

    def purchases(self, fan_id: int) -> list[Purchase]:
        items, urls = self._page_items("collection_items", fan_id)
        try:
            hidden, hidden_urls = self._page_items("hidden_items", fan_id)
        except (requests.RequestException, BandcampError, ValueError) as e:
            self._log(f"  hidden items unavailable: {e}")
            hidden, hidden_urls = [], {}
        urls.update(hidden_urls)

        result: list[Purchase] = []
        seen: set[str] = set()
        for item in items + hidden:
            purchase = Purchase(
                artist=item.get("band_name") or "Unknown artist",
                title=item.get("item_title") or "Untitled",
                type="track" if item.get("tralbum_type") == "t" or item.get("item_type") == "track" else "album",
                sale_item_type=str(item.get("sale_item_type") or ""),
                sale_item_id=int(item.get("sale_item_id") or 0),
                item_id=int(item.get("item_id") or item.get("tralbum_id") or 0),
                redownload_url=None,
            )
            if purchase.sale_key in seen:
                continue
            seen.add(purchase.sale_key)
            purchase.redownload_url = urls.get(purchase.sale_key)
            result.append(purchase)
        return result

    # Downloading

    def formats(self, redownload_url: str) -> dict[str, str]:
        response = self._request("GET", redownload_url)
        response.raise_for_status()
        return download_formats(parse_pagedata(response.text))

    def resolve(self, download_url: str) -> str:
        """Ask statdownload for the final file URL, waiting while Bandcamp prepares it."""
        parts = urlsplit(download_url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k not in (".rand", ".vrs")]
        for attempt in range(1, self.stat_retries + 1):
            stat_query = urlencode(query + [(".rand", str(int(time.time() * 1000))), (".vrs", "1")])
            stat_url = urlunsplit(parts._replace(path=parts.path.replace("/download/", "/statdownload/", 1), query=stat_query))
            response = self._request("GET", stat_url, headers={"Accept": "application/json, text/javascript, */*"})
            response.raise_for_status()
            data = _first_json_object(response.text)
            if data.get("result") == "ok":
                return data.get("download_url") or download_url
            self._log(f"  file not ready ({data.get('result')}), attempt {attempt}/{self.stat_retries}")
            if attempt < self.stat_retries:
                time.sleep(self.stat_wait)
        raise BandcampError("Bandcamp didn't finish preparing the file")

    def fetch(self, url: str, dest) -> str | None:
        """Stream url into dest; return the server's file name, if any."""
        with self._request("GET", url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
            return _filename_from_response(response)
