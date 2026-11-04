import datetime as dt
import json
import re
import tempfile
from pathlib import Path

import pytest

import build


def payload_of(html: str) -> dict:
    return json.loads(re.search(r"const PAYLOAD = (\{.*?\});", html).group(1))


def test_inline_photos_embeds_file_and_requires_credit(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "a.webp").write_bytes(b"RIFF0000WEBP")
    cc = {"credit": "某人", "license": "CC BY-SA 4.0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}
    good = {"days": [{"label": "Day 1", "items": [{"title": "夜市", "photo": {"file": "photos/a.webp", **cc}}]}],
            "transport": {"flights": [{"dir": "去程", "photo": {"file": "photos/a.webp", **cc}}]}}
    assert build.inline_photos(good, tmp_path) == []
    ph = good["days"][0]["items"][0]["photo"]
    # 同一張圖只存一份，機票卡裡的 photo 也會處理
    assert "file" not in ph and ph["ref"] == 0 and good["transport"]["flights"][0]["photo"]["ref"] == 0
    assert len(good["_photos"]) == 1 and good["_photos"][0].startswith("data:image/webp;base64,")
    bad = {"days": [{"label": "Day 1", "items": [
        {"title": "沒署名", "photo": {"file": "photos/a.webp"}},
        {"title": "外部圖", "photo": {"src": "https://example.com/x.jpg", "credit": "x", "license": "x", "url": "x"}},
        {"title": "缺檔", "photo": {"file": "photos/none.webp", "credit": "x", "license": "x", "url": "x"}}]}]}
    errs = build.inline_photos(bad, tmp_path)
    assert any("credit" in e for e in errs) and any("外部" in e for e in errs) and any("不存在" in e for e in errs)


def test_encrypt_roundtrip():
    key = b"k" * 32
    assert build.decrypt(build.encrypt("小鎮 Sample Bridge".encode(), key), key).decode() == "小鎮 Sample Bridge"


def test_key_created_once_and_reused():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "k.txt"
        assert build.load_or_create_key(p) == build.load_or_create_key(p)


def test_templates_have_placeholder():
    for name in ("hub", "trip"):
        assert build.PLACEHOLDER in (build.TEMPLATES / f"{name}.html").read_text(encoding="utf-8")


def test_templates_have_no_external_scripts():
    for name in ("hub", "trip"):
        html = (build.TEMPLATES / f"{name}.html").read_text(encoding="utf-8")
        assert not re.search(r"<script[^>]+src=", html), name


def make_site(d: Path, slug="trip-a") -> Path:
    (d / "a.json").write_text(json.dumps({"title": "秘密行程", "days": []}, ensure_ascii=False), encoding="utf-8")
    site = {"title": "給某人", "intro": "嗨", "items": [
        {"slug": slug, "title": "秘密行程", "date": "11/21", "summary": "摘要", "template": "trip", "data": "a.json"}]}
    (d / "site.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    return d / "site.json"


def test_build_site_outputs_encrypted_hub_and_page():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        key = build.build_site(make_site(d), d / "k.txt", d / "out", now=dt.datetime(2026, 11, 1, 20, 0))
        hub_html = (d / "out" / "index.html").read_text(encoding="utf-8")
        page_html = (d / "out" / "trip-a" / "index.html").read_text(encoding="utf-8")
        for html in (hub_html, page_html):
            assert "秘密行程" not in html and "給某人" not in html
        hub = json.loads(build.decrypt(payload_of(hub_html), key))
        page = json.loads(build.decrypt(payload_of(page_html), key))
        assert hub["items"][0]["slug"] == "trip-a" and hub["updated"] == "2026-11-01 20:00"
        assert page["title"] == "秘密行程" and page["updated"] == "2026-11-01 20:00"
        assert (d / "out" / ".nojekyll").exists()
        sw = (d / "out" / "sw.js").read_text(encoding="utf-8")
        assert '"./trip-a/"' in sw and "秘密行程" not in sw
        mf = json.loads((d / "out" / "manifest.webmanifest").read_text(encoding="utf-8"))
        assert mf["start_url"] == "./" and mf["display"] == "standalone" and "秘密行程" not in json.dumps(mf, ensure_ascii=False)
        assert (d / "out" / "icons" / "maskable-512.png").exists()


def test_hub_marks_versions_and_picks_cover(tmp_path):
    """首頁每份分享帶版本號（判斷「新」用）：重 build 不變、內容改了才變；封面照從那一頁挑、嵌進首頁。"""
    (tmp_path / "p.webp").write_bytes(b"RIFF0000WEBP")
    cc = {"credit": "某人", "license": "CC BY-SA 4.0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}
    trip = {"title": "秘密行程", "days": [{"label": "Day 1", "items": [
        {"title": "a", "photo": {"file": "p.webp", **cc}}, {"title": "b", "star": True, "photo": {"file": "p.webp", "alt": "海", **cc}}]}]}
    (tmp_path / "a.json").write_text(json.dumps(trip, ensure_ascii=False), encoding="utf-8")
    site = {"title": "給某人", "you": "你", "items": [{"slug": "trip-a", "title": "秘密行程", "tag": "旅行", "template": "trip", "data": "a.json"}]}
    (tmp_path / "site.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")

    def hub_of(now):
        key = build.build_site(tmp_path / "site.json", tmp_path / "k.txt", tmp_path / "out", now=now)
        return json.loads(build.decrypt(payload_of((tmp_path / "out" / "index.html").read_text(encoding="utf-8")), key))

    h1, h2 = hub_of(dt.datetime(2026, 11, 1, 20, 0)), hub_of(dt.datetime(2026, 11, 2, 9, 0))
    it = h1["items"][0]
    assert it["ver"] == h2["items"][0]["ver"] and h1["updated"] != h2["updated"]  # 重 build 版本號不變
    assert it["photo"]["alt"] == "海" and h1["_photos"][it["photo"]["ref"]].startswith("data:image/webp")  # 挑標 star 的
    assert h1["you"] == "你" and it["tag"] == "旅行" and it["template"] == "trip"
    trip["days"][0]["items"][0]["title"] = "改了"
    (tmp_path / "a.json").write_text(json.dumps(trip, ensure_ascii=False), encoding="utf-8")
    assert hub_of(dt.datetime(2026, 11, 3, 9, 0))["items"][0]["ver"] != it["ver"]  # 內容改了才變


def test_hub_template_follows_design_rules():
    tpl = (build.TEMPLATES / "hub.html").read_text(encoding="utf-8")
    assert 'content="#fbf6ef" media="(prefers-color-scheme: light)"' in tpl and 'content="#0e141d"' in tpl  # theme-color＝--bg
    assert "interactive-widget=resizes-content" in tpl
    assert "@media (hover: hover) and (pointer: fine)" in tpl and "@media (hover: hover) {" not in tpl
    assert "transition: all" not in tpl and "user-scalable" not in tpl and "maximum-scale" not in tpl
    assert "fetch(" not in tpl


def test_bad_slug_rejected():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        with pytest.raises(ValueError):
            build.build_site(make_site(d, slug="../x"), d / "k.txt", d / "out")


def test_validate_trip_catches_errors():
    good = {"depart": "2026-12-04", "days": [{"label": "Day 1", "date": "12/4（五）", "items": [
        {"time": "10:00", "title": "a", "photo": {"file": "x.webp"}}, {"time": "12:00", "title": "b", "map": "x", "photo": {"file": "x.webp"}}]}],
        "checklist": [{"text": "x", "due": "2026-11-03"}],
        "emergency": {"calls": [{"number": "0912345678"}]}}
    assert build.validate_trip(good) == []
    bad = json.loads(json.dumps(good))
    bad["days"][0]["date"] = "12/4（六）"
    bad["days"][0]["items"][1]["time"] = "09:00"
    bad["checklist"][0]["due"] = "11/3"
    bad["notes"] = ["聯絡 0912-345-678"]
    errs = build.validate_trip(bad)
    assert len(errs) == 4, errs


def test_templates_register_offline_worker():
    for name in ("hub", "trip"):
        assert "serviceWorker" in (build.TEMPLATES / f"{name}.html").read_text(encoding="utf-8")


def test_trip_template_keeps_own_notes_local():
    tpl = (build.TEMPLATES / "trip.html").read_text(encoding="utf-8")
    assert 'const MINE = "mine:"' in tpl and "localStorage.setItem(MINE" in tpl
    assert "fetch(" not in tpl  # 勾選和筆記不會送出去


def test_validate_trip_requires_photo_and_known_brand():
    d = {"depart": "2026-12-04", "brands": {"taxi": {}}, "days": [{"label": "Day 1", "date": "12/4（五）", "items": [
        {"time": "09:00", "title": "吃早餐"}, {"time": "10:00", "title": "叫車", "brand": "uber", "photo": {"file": "x.webp"}}]}]}
    errs = build.validate_trip(d)
    assert any("吃早餐 沒有照片" in e for e in errs) and any("uber" in e for e in errs) and len(errs) == 2, errs


def test_inline_logos(tmp_path):
    (tmp_path / "g.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>', encoding="utf-8")
    (tmp_path / "bad.svg").write_text('<svg><script>alert(1)</script></svg>', encoding="utf-8")
    d = {"brands": {"taxi": {"name": "Taxi", "file": "g.svg", "url": "https://commons.wikimedia.org/x"}}}
    assert build.inline_logos(d, tmp_path) == []
    assert d["_logos"]["taxi"].startswith("data:image/svg+xml;base64,") and "file" not in d["brands"]["taxi"]
    bad = {"brands": {"a": {"file": "bad.svg", "url": "u"}, "b": {"file": "none.png"}}}
    errs = build.inline_logos(bad, tmp_path)
    assert any("script" in e for e in errs) and any("url" in e for e in errs) and any("不存在" in e for e in errs)


def test_validate_trip_blocks_todo():
    d = {"depart": "2026-12-04", "days": [{"label": "Day 1", "date": "12/4（五）", "title": "TODO", "items": []}]}
    assert any("TODO" in e for e in build.validate_trip(d))


def test_validate_trip_blocks_impossible_leg():
    d = {"depart": "2026-12-04", "days": [{"label": "Day 2", "date": "12/5（六）", "items": [
        {"time": "15:30", "title": "海灘", "map": "a", "geo": [1.0, 1.0], "photo": {"file": "x.webp"}},
        {"time": "15:50", "title": "夜市", "map": "b", "geo": [1.1, 1.1], "leg": {"from": 0, "km": 20, "min": 38}, "photo": {"file": "x.webp"}}]}]}
    errs = build.validate_trip(d)
    assert any("排不下" in e for e in errs), errs
    d["days"][0]["items"][1]["time"] = "16:30"
    assert build.validate_trip(d) == []


def test_embed_fonts_subsets_to_page_text(tmp_path):
    font = Path(__file__).parent / "fonts" / "DMSerifDisplay-Regular.ttf"
    if not font.exists():
        pytest.skip("沒有字型檔")
    data = {"title": "Day 1", "_photos": ["data:image/webp;base64,AAAA"], "days": [{"items": [{"time": "09:00"}]}]}
    text = build.page_text(data, "模板字")
    assert "Day 1" in text and "09:00" in text and "模板字" in text and "base64" not in text  # 不收照片資料
    assert build.embed_fonts(data, {"num": str(font)}, tmp_path, text) == []
    raw = __import__("base64").b64decode(data["_fonts"]["num"])
    assert raw[:4] == b"wOF2" and len(raw) < font.stat().st_size  # 縮過、是 woff2
    assert build.embed_fonts({}, {"num": "nope.ttf"}, tmp_path, "x")  # 找不到檔會回錯誤
    assert build.embed_fonts({}, {}, tmp_path, "x") == []  # 沒設定就跳過


def test_photo_src_is_stripped(tmp_path):
    """第二道防線：photo／cover 的 src（外部網址）一律拿掉，頁面不會從第三方載圖。"""
    (tmp_path / "p.webp").write_bytes(b"RIFF0000WEBP")
    cc = {"credit": "x", "license": "CC0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}
    data = {"cover": {"file": "p.webp", "src": "https://evil.example/c.jpg", **cc},
            "days": [{"label": "Day 1", "items": [{"title": "a", "photo": {"file": "p.webp", "src": "https://evil.example/x.jpg", **cc}}]}]}
    assert build.inline_photos(data, tmp_path) == []
    assert "src" not in data["days"][0]["items"][0]["photo"] and "src" not in data["cover"]
    ph = build.absolute_photo({"file": "p.webp", "src": "https://evil.example/y.jpg", **cc}, tmp_path)
    assert "src" not in ph


def test_build_removes_pages_no_longer_listed(tmp_path):
    """拿掉一頁後，輸出資料夾裡那頁也要刪掉，不然 push（git add -A）會留著舊頁。"""
    site_path = make_site(tmp_path)
    site = json.loads(site_path.read_text(encoding="utf-8"))
    site["items"].append(dict(site["items"][0], slug="trip-b"))
    site_path.write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    build.build_site(site_path, tmp_path / "k.txt", out)
    (out / ".git").mkdir()
    (out / "not-a-slug_").mkdir()
    assert (out / "trip-b" / "index.html").exists()
    site["items"].pop()
    site_path.write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    build.build_site(site_path, tmp_path / "k.txt", out)
    assert not (out / "trip-b").exists()
    assert (out / "trip-a" / "index.html").exists() and (out / ".git").is_dir()
    assert (out / "icons").is_dir() and (out / "not-a-slug_").is_dir()   # 不像 slug 的資料夾不動


def test_forged_photos_and_ref_are_not_trusted(tmp_path):
    """資料裡偽造 _photos／_logos 加上 cover.ref：build 不沿用，輸出不會有外部網址。"""
    (tmp_path / "p.webp").write_bytes(b"RIFF0000WEBP")
    cc = {"credit": "x", "license": "CC0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}
    data = {"title": "t", "days": [], "cover": {"file": "p.webp", "ref": 5, **cc},
            "_photos": ["https://evil.example/x.jpg"], "_logos": {"a": "https://evil.example/l.svg"},
            "_fonts": {"hand": "https://evil.example/f.woff2"}, "picks": {"items": [{"ref": 0, "name": "x"}]}}
    (tmp_path / "a.json").write_text(json.dumps(data), encoding="utf-8")
    site = {"title": "s", "items": [{"slug": "trip-a", "title": "t", "template": "trip", "data": "a.json"}]}
    (tmp_path / "site.json").write_text(json.dumps(site), encoding="utf-8")
    key = build.build_site(tmp_path / "site.json", tmp_path / "k.txt", tmp_path / "out")
    for f in (tmp_path / "out" / "trip-a" / "index.html", tmp_path / "out" / "index.html"):
        page = json.loads(build.decrypt(payload_of(f.read_text(encoding="utf-8")), key))
        assert "evil.example" not in json.dumps(page)
        assert all(p.startswith("data:image/") for p in page.get("_photos", []))
    page = json.loads(build.decrypt(payload_of((tmp_path / "out" / "trip-a" / "index.html").read_text(encoding="utf-8")), key))
    assert page["cover"]["ref"] == 0 and "file" not in page["cover"] and "_logos" not in page
    assert "ref" not in page["picks"]["items"][0]
    # 只有 ref、沒有 file 的 cover：build 擋下來
    data["cover"] = {"ref": 0, **cc}
    (tmp_path / "a.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="本機檔"):
        build.build_site(tmp_path / "site.json", tmp_path / "k.txt", tmp_path / "out")


def test_inline_photos_resets_forged_pool(tmp_path):
    data = {"_photos": ["https://evil.example/x.jpg"], "cover": {"ref": 0}}
    build.inline_photos(data, tmp_path)
    assert "_photos" not in data and "ref" not in data["cover"]


def test_prune_needs_previous_build_markers(tmp_path):
    """--out 打錯（例如 private）：沒有上次 build 的 sw.js＋manifest 就不刪任何東西。"""
    out = tmp_path / "private"
    (out / "pages" / "busan").mkdir(parents=True)
    (out / "pages" / "busan" / "trip.json").write_text("{}", encoding="utf-8")
    (out / "old-page").mkdir()
    (out / "old-page" / "index.html").write_text("x", encoding="utf-8")
    build.build_site(make_site(tmp_path), tmp_path / "k.txt", out)
    assert (out / "pages" / "busan" / "trip.json").exists() and (out / "old-page" / "index.html").exists()


def test_prune_keeps_dirs_with_non_build_files(tmp_path):
    site_path = make_site(tmp_path)
    out = tmp_path / "out"
    build.build_site(site_path, tmp_path / "k.txt", out)       # 有標記了
    (out / "notes").mkdir()
    (out / "notes" / "index.html").write_text("x", encoding="utf-8")
    (out / "notes" / "todo.txt").write_text("不是 build 產物", encoding="utf-8")
    (out / "pages").mkdir()
    (out / "pages" / "trip.json").write_text("{}", encoding="utf-8")
    (out / "gone").mkdir()
    (out / "gone" / "index.html").write_text("x", encoding="utf-8")
    build.build_site(site_path, tmp_path / "k.txt", out)
    assert (out / "notes" / "todo.txt").exists() and (out / "pages" / "trip.json").exists()
    assert not (out / "gone").exists()


def _price_site(tmp_path, price_ref=None, price=None):
    trip = {"title": "秘密行程", "days": []}
    if price_ref:
        trip["price_track_file"] = price_ref
    (tmp_path / "a.json").write_text(json.dumps(trip, ensure_ascii=False), encoding="utf-8")
    if price is not None:
        (tmp_path / "price_track.json").write_text(json.dumps(price, ensure_ascii=False), encoding="utf-8")
    site = {"title": "給某人", "items": [{"slug": "trip-a", "title": "秘密行程", "template": "trip", "data": "a.json"}]}
    (tmp_path / "site.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")


def _page_of(tmp_path, now):
    key = build.build_site(tmp_path / "site.json", tmp_path / "k.txt", tmp_path / "out", now=now)
    html = (tmp_path / "out" / "trip-a" / "index.html").read_text(encoding="utf-8")
    return json.loads(build.decrypt(payload_of(html), key)), json.loads(
        build.decrypt(payload_of((tmp_path / "out" / "index.html").read_text(encoding="utf-8")), key))


PRICE = {"updated": "2026-11-03 20:00", "currency": "TWD", "notes": ["說明"], "booked": {"flight": None, "hotel": None},
         "series": [{"date": "2026-11-01", "flight_total": 10000, "hotel_total": 5000, "total": 15000, "note": ""},
                    {"date": "2026-11-02", "flight_total": 9800, "hotel_total": None, "total": None, "note": "x"}]}


def test_price_track_file_is_loaded_into_page(tmp_path):
    _price_site(tmp_path, "price_track.json", PRICE)
    page, hub = _page_of(tmp_path, dt.datetime(2026, 11, 3, 20, 0))
    assert page["price_track"]["series"][0]["total"] == 15000 and "price_track_file" not in page
    assert "price_track" not in json.dumps(hub)


def test_price_track_missing_file_warns_and_skips(tmp_path, capsys):
    _price_site(tmp_path, "price_track.json", None)
    page, _ = _page_of(tmp_path, dt.datetime(2026, 11, 3, 20, 0))
    assert "price_track" not in page and "price_track_file" not in page
    assert "價格追蹤檔不存在" in capsys.readouterr().out


def test_no_price_track_file_no_field(tmp_path):
    _price_site(tmp_path)
    page, _ = _page_of(tmp_path, dt.datetime(2026, 11, 3, 20, 0))
    assert "price_track" not in page


def test_price_track_bad_shape_fails_build(tmp_path):
    _price_site(tmp_path, "price_track.json", {"series": [{"date": "11/1", "total": "abc"}]})
    with pytest.raises(ValueError, match="價格追蹤"):
        build.build_site(tmp_path / "site.json", tmp_path / "k.txt", tmp_path / "out")


def test_price_track_does_not_change_hub_version(tmp_path):
    _price_site(tmp_path, "price_track.json", PRICE)
    _, h1 = _page_of(tmp_path, dt.datetime(2026, 11, 3, 20, 0))
    p2 = json.loads(json.dumps(PRICE)); p2["series"][0]["total"] = 20000
    (tmp_path / "price_track.json").write_text(json.dumps(p2), encoding="utf-8")
    _, h2 = _page_of(tmp_path, dt.datetime(2026, 11, 4, 20, 0))
    assert h1["items"][0]["ver"] == h2["items"][0]["ver"]


def test_trip_template_has_price_pane_without_external_resources():
    tpl = (build.TEMPLATES / "trip.html").read_text(encoding="utf-8")
    assert 'key: "price"' in tpl and "function pricePane" in tpl and "function priceChart" in tpl
    assert not re.search(r"https?://[^\s\"']+\.(js|css|png)", tpl)


@pytest.mark.parametrize("ref", ["C:/Windows/win.ini", "C:\\Windows\\win.ini", "/etc/passwd", "../price_track.json", "sub/../../price_track.json"])
def test_price_track_file_outside_page_dir_is_refused(tmp_path, ref):
    page = tmp_path / "page"
    page.mkdir()
    (tmp_path / "price_track.json").write_text(json.dumps(PRICE), encoding="utf-8")
    data = {"price_track_file": ref}
    errs = build.load_price_track(data, page, warn=lambda m: None)
    assert errs and "price_track" not in data and "price_track_file" not in data


def test_price_track_file_in_subfolder_still_works(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "p.json").write_text(json.dumps(PRICE), encoding="utf-8")
    data = {"price_track_file": "sub/p.json"}
    assert build.load_price_track(data, tmp_path) == [] and data["price_track"]["series"]
