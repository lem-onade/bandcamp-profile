import json
from pathlib import Path

import pytest

from bandcamp_sync import cli, sync as sync_mod
from bandcamp_sync.client import BandcampError, Client, Purchase, download_formats, parse_pagedata
from bandcamp_sync.state import STATE_NAME
from bandcamp_sync.sync import render, sanitize

from fake_bandcamp import GOOD_COOKIE, FakeBandcamp, FakeItem, demo_items, serve


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(sync_mod, "PAUSE", 0)
    monkeypatch.delenv("BANDCAMP_SYNC_COOKIE_FILE", raising=False)


@pytest.fixture
def cookie(tmp_path):
    path = tmp_path / "cookie"
    path.write_text(GOOD_COOKIE + "\n")
    return path


def start(monkeypatch, items, **kwargs):
    fake = FakeBandcamp(items, **kwargs)
    server = serve(fake)
    monkeypatch.setenv("BANDCAMP_SYNC_BASE_URL", fake.base_url)
    return fake, server


def run(cookie, out, *args):
    return cli.main(["--cookie-file", str(cookie), "-o", str(out), *args])


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# Cookie loading


def test_cookie_raw_value(tmp_path):
    path = tmp_path / "c"
    path.write_text("  abc%09def \n")
    assert cli.load_cookie(path, "x") == "abc%09def"


def test_cookie_identity_form(tmp_path):
    path = tmp_path / "c"
    path.write_text("identity=abc%09def\n")
    assert cli.load_cookie(path, "x") == "abc%09def"


def test_cookie_lookup_order(tmp_path, monkeypatch):
    assert cli.cookie_path("/a")[0] == Path("/a")
    monkeypatch.setenv("BANDCAMP_SYNC_COOKIE_FILE", "/b")
    assert cli.cookie_path(None)[0] == Path("/b")
    monkeypatch.delenv("BANDCAMP_SYNC_COOKIE_FILE")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.cookie_path(None)[0] == tmp_path / ".config/bandcamp-sync/cookie"


def test_missing_cookie_file_exits_2(tmp_path, capsys):
    missing = tmp_path / "nope"
    assert cli.main(["--cookie-file", str(missing), "-o", str(tmp_path / "out")]) == 2
    err = capsys.readouterr().err
    assert str(missing) in err and "identity" in err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


def test_rejected_cookie_exits_2_without_printing_it(tmp_path, monkeypatch, capsys):
    start(monkeypatch, demo_items())
    path = tmp_path / "cookie"
    path.write_text("identity=expired-secret-value")
    assert run(path, tmp_path / "out") == 2
    captured = capsys.readouterr()
    assert "rejected" in captured.err and str(path) in captured.err
    assert "expired-secret-value" not in captured.err + captured.out
    assert not (tmp_path / "out").exists()


def test_fan_id_falls_back_to_profile_page(monkeypatch):
    start(monkeypatch, demo_items(), summary_has_fan_id=False)
    assert Client(GOOD_COOKIE).fan_id() == 3950257


# Listing


def test_collection_pages_and_hidden_items(monkeypatch):
    items = [
        FakeItem(1, "A", "One"),
        FakeItem(2, "B", "Two", type="track"),
        FakeItem(3, "C", "Three"),
        FakeItem(4, "D", "Hidden", hidden=True),
        FakeItem(5, "E", "No link", downloadable=False),
    ]
    fake, _ = start(monkeypatch, items, page_size=2)
    purchases = Client(GOOD_COOKIE).purchases(3950257)
    assert [p.title for p in purchases] == ["One", "Two", "Three", "No link", "Hidden"]
    assert fake.requests.count("POST /api/fancollection/1/collection_items") == 2
    assert fake.requests.count("POST /api/fancollection/1/hidden_items") == 1
    assert purchases[1].type == "track" and purchases[1].sale_key == "p2"
    assert purchases[3].redownload_url is None
    assert "sitem_id=4" in purchases[4].redownload_url


# Redownload page parsing


def test_redownload_page_formats():
    blob = json.loads((Path(__file__).parent / "samples/redownload_pagedata.json").read_text())
    blob["digital_items"][0]["downloads"] = {"flac": {"url": "https://x/download/album?enc=flac"}, "mp3-320": {"url": "u2"}}
    page = f'<div class="x" id="pagedata" data-blob="{json.dumps(blob).replace("&", "&amp;").replace(chr(34), "&quot;")}"></div>'
    formats = download_formats(parse_pagedata(page))
    assert formats["flac"] == "https://x/download/album?enc=flac"
    assert set(formats) == {"flac", "mp3-320"}


def test_redownload_page_without_pagedata():
    with pytest.raises(BandcampError):
        parse_pagedata("<html></html>")


def test_missing_format_is_reported(tmp_path, monkeypatch, cookie, capsys):
    start(monkeypatch, [FakeItem(1, "A", "One", formats=("mp3-320",))])
    assert run(cookie, tmp_path / "out") == 1
    assert "failed: format flac not offered (available: mp3-320)" in capsys.readouterr().out


# Full sync


def test_full_sync_then_second_run(tmp_path, monkeypatch, cookie, capsys):
    start(monkeypatch, demo_items())
    out = tmp_path / "out"
    assert run(cookie, out) == 0
    first = capsys.readouterr().out
    assert "[1/2] Ana Roxanne — Because of a Flower … downloaded" in first
    assert "[2/2] Khruangbin — Pelota … downloaded" in first
    assert "2 downloaded, 0 already synced, 0 skipped, 0 failed, 0 not downloadable" in first

    album = out / "Ana Roxanne" / "Because of a Flower"
    assert sorted(p.name for p in album.iterdir()) == [
        "Ana Roxanne - Because of a Flower - 01 Song 1.flac",
        "Ana Roxanne - Because of a Flower - 02 Song 2.flac",
        "cover.jpg",
    ]
    assert (out / "Khruangbin" / "Pelota.flac").read_bytes() == b"audio of Pelota"
    assert not [p for p in out.rglob("*") if p.name.endswith((".part", ".tmp"))]

    state = json.loads((out / STATE_NAME).read_text())
    assert set(state) == {"p1001:flac", "p1002:flac"}
    assert state["p1002:flac"]["path"] == "Khruangbin/Pelota.flac"
    assert state["p1001:flac"]["artist"] == "Ana Roxanne" and state["p1001:flac"]["downloaded_at"]

    before = tree(out)
    assert run(cookie, out) == 0
    second = capsys.readouterr().out
    assert second.count("already synced") == 3  # two lines + the summary
    assert "0 downloaded, 2 already synced" in second
    assert tree(out) == before


def test_other_format_downloads_again(tmp_path, monkeypatch, cookie, capsys):
    start(monkeypatch, demo_items())
    out = tmp_path / "out"
    run(cookie, out)
    assert run(cookie, out, "-f", "mp3-320", "-t", "{format}/{artist}/{title}") == 0
    assert (out / "mp3-320" / "Khruangbin" / "Pelota.flac").exists()  # extension comes from the file served
    assert "2 downloaded" in capsys.readouterr().out


def test_one_failure_others_done(tmp_path, monkeypatch, cookie, capsys):
    items = [FakeItem(1, "A", "Good"), FakeItem(2, "B", "Broken", fail="file"), FakeItem(3, "C", "Bad zip", fail="zip")]
    start(monkeypatch, items)
    out = tmp_path / "out"
    assert run(cookie, out) == 1
    text = capsys.readouterr().out
    assert "B — Broken … failed: HTTP 500" in text
    assert "C — Bad zip … failed:" in text
    assert "1 downloaded, 0 already synced, 0 skipped, 2 failed" in text
    assert set(json.loads((out / STATE_NAME).read_text())) == {"p1:flac"}
    assert tree(out) == sorted([STATE_NAME, "A", "A/Good", "A/Good/A - Good - 01 Song 1.flac",
                                "A/Good/A - Good - 02 Song 2.flac", "A/Good/cover.jpg", "B", "C"])


def test_statdownload_retries_until_ready(tmp_path, monkeypatch, cookie, capsys):
    monkeypatch.setattr(Client, "__init__", _fast_client_init(Client.__init__))
    start(monkeypatch, [FakeItem(1, "A", "Slow", not_ready=2)])
    assert run(cookie, tmp_path / "out") == 0
    assert "1 downloaded" in capsys.readouterr().out


def _fast_client_init(original):
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.stat_wait = 0
    return init


def test_dry_run_writes_nothing(tmp_path, monkeypatch, cookie, capsys):
    fake, _ = start(monkeypatch, demo_items())
    out = tmp_path / "out"
    assert run(cookie, out, "--dry-run") == 0
    text = capsys.readouterr().out
    assert "would download to Ana Roxanne/Because of a Flower" in text
    assert "would download to Khruangbin/Pelota.flac" in text
    assert "dry run: 2 to download" in text
    assert not out.exists()
    assert not any(r.startswith("GET /download") or "files" in r for r in fake.requests)


def test_limit(tmp_path, monkeypatch, cookie, capsys):
    start(monkeypatch, demo_items())
    out = tmp_path / "out"
    assert run(cookie, out, "--limit", "1") == 0
    assert "1 downloaded" in capsys.readouterr().out
    assert set(json.loads((out / STATE_NAME).read_text())) == {"p1001:flac"}


def test_not_downloadable_counted(tmp_path, monkeypatch, cookie, capsys):
    start(monkeypatch, [FakeItem(1, "A", "Gone", downloadable=False)])
    assert run(cookie, tmp_path / "out") == 0
    text = capsys.readouterr().out
    assert "A — Gone … not downloadable" in text and "1 not downloadable" in text


# Templates and existing files


def test_template_sanitises_values():
    p = Purchase("AC/DC", "../../etc", "album", "p", 1, 42, None)
    rel = render("{artist}/{title}", p, "flac")
    assert rel == Path("AC_DC/___.._etc")
    assert ".." not in rel.parts
    assert sanitize('a<b>c:"d|e?*') == "a_b_c__d_e__"
    assert sanitize(".hidden") == "_hidden"
    assert sanitize("CON") == "_CON"
    assert render("{type}/{format}/{id} {title}", p, "mp3-v0") == Path("album/mp3-v0/42 ___.._etc")


def test_bad_template_rejected(tmp_path, cookie, capsys):
    assert run(cookie, tmp_path / "o", "-t", "{artist}/{nope}") == 2
    assert "unknown placeholder {nope}" in capsys.readouterr().err
    assert run(cookie, tmp_path / "o", "-t", "../{title}") == 2


def test_existing_destination_not_overwritten(tmp_path, monkeypatch, cookie, capsys):
    fake, _ = start(monkeypatch, demo_items())
    out = tmp_path / "out"
    track = out / "Khruangbin" / "Pelota.flac"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"mine")
    album = out / "Ana Roxanne" / "Because of a Flower"
    album.mkdir(parents=True)

    assert run(cookie, out) == 0
    text = capsys.readouterr().out
    assert text.count("skipped: exists") == 2
    assert track.read_bytes() == b"mine" and list(album.iterdir()) == []
    assert set(json.loads((out / STATE_NAME).read_text())) == {"p1001:flac", "p1002:flac"}
    assert not any("files" in r for r in fake.requests)

    # --force ignores the record but still never overwrites
    assert run(cookie, out, "--force") == 0
    assert capsys.readouterr().out.count("skipped: exists") == 2
    assert track.read_bytes() == b"mine"


def test_help_lists_every_flag(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = capsys.readouterr().out
    for flag in ["-o", "--output", "-f", "--format", "-t", "--template", "-n", "--dry-run", "--limit",
                 "--force", "--cookie-file", "-v", "--verbose"]:
        assert flag in text
