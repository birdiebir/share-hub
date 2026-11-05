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
    # 註冊程式在共用層 core.js，模板只呼叫 registerSW(路徑)，所以檢查展開共用層之後的模板
    for name, path in (("hub", "./sw.js"), ("trip", "../sw.js")):
        assert f'registerSW("{path}")' in (build.TEMPLATES / f"{name}.html").read_text(encoding="utf-8")
        assert "serviceWorker" in build.page_template(name)


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


# ===== 共用層與 article／resources 模板 =====

NEW_TEMPLATES = ("article", "resources")
CC = {"credit": "x", "license": "CC0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}
PNG1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def _new_site(tmp_path, article=None, resources=None):
    (tmp_path / "p.png").write_bytes(PNG1)
    art = {"title": "示範文章", "body": "# 標題\n\n內文 ![圖](photo:甲)", "photos": {"甲": {"file": "p.png", **CC}}}
    res = {"title": "示範清單", "items": [{"title": "甲", "url": "https://example.com/a", "tags": ["x"]}]}
    (tmp_path / "a.json").write_text(json.dumps(article or art, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps(resources or res, ensure_ascii=False), encoding="utf-8")
    site = {"title": "給某人", "items": [
        {"slug": "art", "title": "示範文章", "template": "article", "data": "a.json"},
        {"slug": "res", "title": "示範清單", "template": "resources", "data": "r.json"}]}
    (tmp_path / "site.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "site.json"


def test_new_templates_have_placeholder_parts_and_no_external_resources():
    for name in NEW_TEMPLATES:
        raw = (build.TEMPLATES / f"{name}.html").read_text(encoding="utf-8")
        assert raw.count(build.PLACEHOLDER) == 1
        assert "/*__PART:base.css__*/" in raw and "/*__PART:core.js__*/" in raw
        full = build.page_template(name)
        assert "__PART" not in full and "serviceWorker" in full
        assert not re.search(r"<script[^>]+src=", full) and "fetch(" not in full
        assert not re.search(r"<link[^>]+rel=.stylesheet", full) and "@import" not in full
        urls = re.findall(r"https?://[^\s\"')]+", full)
        assert all(u.startswith("http://www.w3.org") for u in urls), (name, urls)   # 只剩 SVG 命名空間
        assert "innerHTML" not in raw  # 內容一律 createElement／textContent；ICONS 的 SVG 在共用層 core.js


def test_shared_parts_missing_raises():
    with pytest.raises(ValueError, match="共用片段不存在"):
        build.inject_parts("/*__PART:nope.css__*/")
    one = build.inject_parts("/*__PART:base.css__*/")
    assert build.inject_parts("a/*__PART:base.css__*/b/*__PART:base.css__*/") == "a" + one + "b" + one   # 同一標記出現兩次照換


def test_new_templates_build_and_payload_decrypts(tmp_path):
    key = build.build_site(_new_site(tmp_path), tmp_path / "k.txt", tmp_path / "out", now=dt.datetime(2026, 11, 5, 9, 0))
    for slug, title in (("art", "示範文章"), ("res", "示範清單")):
        html = (tmp_path / "out" / slug / "index.html").read_text(encoding="utf-8")
        assert title not in html and "__PART" not in html
        page = json.loads(build.decrypt(payload_of(html), key))
        assert page["title"] == title and page["updated"] == "2026-11-05 09:00"
    art = json.loads(build.decrypt(payload_of((tmp_path / "out" / "art" / "index.html").read_text(encoding="utf-8")), key))
    assert art["photos"]["甲"]["ref"] == 0 and "file" not in art["photos"]["甲"] and art["_photos"][0].startswith("data:image/png;base64,")
    hub = json.loads(build.decrypt(payload_of((tmp_path / "out" / "index.html").read_text(encoding="utf-8")), key))
    assert {i["slug"]: i["template"] for i in hub["items"]} == {"art": "article", "res": "resources"}
    assert hub["items"][0]["photo"]["ref"] is not None   # 文章沒有 cover：用 photos 第一張當首頁封面
    assert '"./art/"' in (tmp_path / "out" / "sw.js").read_text(encoding="utf-8")


def test_article_validation():
    ok = {"title": "t", "body": "x"}
    assert build.validate_article(ok) == []
    assert build.validate_article({"title": "t", "sections": [{"title": "a", "body": "b"}]}) == []
    assert any("標題" in e for e in build.validate_article({"body": "x"}))
    assert any("至少" in e for e in build.validate_article({"title": "t"}))
    assert any("TODO" in e for e in build.validate_article({"title": "t", "body": "TODO 補"}))
    assert any("手機" in e for e in build.validate_article({"title": "t", "body": "0912-345-678"}))
    assert any("身分證" in e for e in build.validate_article({"title": "t", "body": "A123456789"}))
    assert any("https" in e for e in build.validate_article({**ok, "sources": [{"text": "x", "url": "http://a.com"}]}))
    assert any("第 1 段" in e for e in build.validate_article({"title": "t", "sections": [{"body": "b"}]}))


def test_resources_validation():
    ok = {"title": "t", "items": [{"title": "a", "url": "https://example.com"}]}
    assert build.validate_resources(ok) == []
    for bad_url in ("http://a.com", "javascript:alert(1)", "//a.com", "ftp://a", "", "https://", "https://a b"):
        assert any("https" in e for e in build.validate_resources({"title": "t", "items": [{"title": "a", "url": bad_url}]})), bad_url
    assert any("title" in e for e in build.validate_resources({"title": "t", "items": [{"url": "https://a.com"}]}))
    assert any("標題" in e for e in build.validate_resources({"items": ok["items"]}))
    assert any("TODO" in e for e in build.validate_resources({"title": "t", "items": [{"title": "a", "url": "https://a.com", "note": "TODO"}]}))
    assert any("手機" in e for e in build.validate_resources({"title": "t", "items": [{"title": "a", "url": "https://a.com", "note": "0912345678"}]}))
    assert any("tags" in e for e in build.validate_resources({"title": "t", "items": [{"title": "a", "url": "https://a.com", "tags": "x"}]}))


@pytest.mark.parametrize("which,data,msg", [
    ("article", {"body": "x"}, "標題"),
    ("article", {"title": "t", "body": "TODO"}, "TODO"),
    ("resources", {"title": "t", "items": [{"title": "a", "url": "http://a.com"}]}, "https"),
    ("resources", {"title": "t", "items": [{"title": "a", "url": "https://a.com", "note": "A123456789"}]}, "身分證")])
def test_new_templates_build_rejects_bad_data(tmp_path, which, data, msg):
    site = _new_site(tmp_path, article=data if which == "article" else None, resources=data if which == "resources" else None)
    with pytest.raises(ValueError, match=msg):
        build.build_site(site, tmp_path / "k.txt", tmp_path / "out")


def test_new_template_photos_need_credit_and_local_file(tmp_path):
    bad = {"title": "t", "body": "x", "photos": {"甲": {"file": "p.png"}, "乙": {"src": "https://evil.example/x.png", **CC}}}
    with pytest.raises(ValueError) as e:
        build.build_site(_new_site(tmp_path, article=bad), tmp_path / "k.txt", tmp_path / "out")
    assert "credit" in str(e.value) and "外部網址" in str(e.value)


def test_photos_ref_cannot_be_forged(tmp_path):
    """資料裡寫死的 _photos、photos[名].ref／src 都不被信任（跟 trip 一樣由 build 指派）。"""
    forged = {"title": "t", "body": "x", "_photos": ["https://evil.example/x.png"],
              "photos": {"甲": {"file": "p.png", "ref": 0, "src": "https://evil.example/y.png", **CC}}}
    key = build.build_site(_new_site(tmp_path, article=forged), tmp_path / "k.txt", tmp_path / "out")
    art = json.loads(build.decrypt(payload_of((tmp_path / "out" / "art" / "index.html").read_text(encoding="utf-8")), key))
    assert "src" not in art["photos"]["甲"] and all(p.startswith("data:image/png") for p in art["_photos"])


def test_hub_template_icons_and_labels_for_new_templates():
    tpl = (build.TEMPLATES / "hub.html").read_text(encoding="utf-8")
    assert 'article: "doc"' in tpl and 'resources: "link"' in tpl
    labels = re.search(r"const TEMPLATE_LABEL = \{[^}]*\}", tpl).group(0)
    assert "文章" in labels and "清單" in labels and "trip" not in labels   # 行程不加小標，現站畫面不變


def test_pick_cover_for_new_templates():
    ph = {"file": "a.png", **CC}
    assert build.pick_cover({"photos": {"a": ph}}) is ph
    assert build.pick_cover({"items": [{"title": "x"}, {"title": "y", "photo": ph}]}) is ph
    assert build.pick_cover({"cover": {"file": "c.png"}, "photos": {"a": ph}}) == {"file": "c.png"}
    assert build.pick_cover({"title": "no photos"}) is None


# ===== QC 修正（2026-11-05）：photos 型別、photo url https、內文警告 =====

@pytest.mark.parametrize("photos", [[{"src": "https://evil.example/a.png", **CC}], "photos", 5, {"0": {"file": "p.png", **CC}},
                                    {"a b": {"file": "p.png", **CC}}, {"x(y)": {"file": "p.png", **CC}}, {"__proto__": {"file": "p.png", **CC}},
                                    {"甲": "not-an-object"}])
def test_bad_photos_shapes_blocked_for_article_and_resources(tmp_path, photos):
    art = {"title": "t", "body": "![x](photo:0)", "photos": photos}
    res = {"title": "t", "items": [{"title": "a", "url": "https://a.com"}], "photos": photos}
    assert any("photos" in e for e in build.validate_article(art))
    assert any("photos" in e for e in build.validate_resources(res))
    with pytest.raises(ValueError, match="photos"):
        build.build_site(_new_site(tmp_path, article=art), tmp_path / "k.txt", tmp_path / "out")


def test_strip_src_removes_src_under_any_photos_type():
    for photos in ([{"src": "https://evil.example/a.png"}], {"a": {"src": "https://evil.example/b.png", "n": {"src": "x"}}}, [[{"src": "x"}]]):
        d = {"photos": photos, "x": {"photos": [{"src": "y"}]}}
        build.strip_src(d)
        assert "evil.example" not in json.dumps(d) and '"src"' not in json.dumps(d)


def test_array_photos_never_ship_external_src_even_without_validators(tmp_path, monkeypatch):
    monkeypatch.setitem(build.VALIDATORS, "article", lambda d: [])   # 繞過驗證：build 這一關自己也要拿掉 src
    art = {"title": "t", "body": "![x](photo:0)", "photos": [{"src": "https://evil.example/a.png", "credit": "x", "license": "x", "url": "https://a.com"}]}
    key = build.build_site(_new_site(tmp_path, article=art), tmp_path / "k.txt", tmp_path / "out")
    page = json.loads(build.decrypt(payload_of((tmp_path / "out" / "art" / "index.html").read_text(encoding="utf-8")), key))
    assert "evil.example" not in json.dumps(page)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://a.com/x", "//a.com", "data:text/html,x", "x"])
def test_photo_url_must_be_https(tmp_path, url):
    (tmp_path / "p.png").write_bytes(PNG1)
    d = {"cover": {"file": "p.png", "credit": "c", "license": "l", "url": url}}
    assert any("https" in e for e in build.inline_photos(d, tmp_path))
    ok = {"cover": {"file": "p.png", "credit": "c", "license": "l", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}}
    assert build.inline_photos(ok, tmp_path) == []


def test_article_warnings_listed_and_build_prints_them(tmp_path, capsys):
    art = {"title": "t", "body": "![a](photo:不存在) ![b](https://evil.example/x.png) [c](javascript:alert(1)) [d](https://ok.com) [e](tel:+886212345678) ![ok](photo:甲)",
           "sections": [{"title": "s", "body": "[f](http://plain.com)"}], "photos": {"甲": {"file": "p.png", **CC}}}
    w = build.article_warnings(art)
    assert len(w) == 4 and any("不存在" in x for x in w) and any("evil.example" in x for x in w) and any("javascript" in x for x in w) and any("http://plain.com" in x for x in w)
    build.build_site(_new_site(tmp_path, article=art), tmp_path / "k.txt", tmp_path / "out")   # 只警告、不擋
    out = capsys.readouterr().out
    assert out.count("警告") == 4 and "art：" in out
    assert build.article_warnings({"title": "t", "body": "![ok](photo:甲) [d](https://ok.com)", "photos": {"甲": {}}}) == []
