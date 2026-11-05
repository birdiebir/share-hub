"""article／resources 模板的瀏覽器測試（Edge＋Playwright＋本機 HTTP server）。

站放在 /site/ 底下，金鑰放網址 #k=。沒有 Playwright 或 Microsoft Edge 時整份跳過。
"""
import base64
import functools
import http.server
import json
import re
import threading
from pathlib import Path

import pytest

import build

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(scope="module")
def edge():
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
    except Exception:
        pytest.skip("沒有 Playwright")
    try:
        browser = pw.chromium.launch(channel="msedge")
    except Exception:
        pw.stop()
        pytest.skip("沒有 Microsoft Edge")
    yield browser
    browser.close()
    pw.stop()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    """回傳 start(www) -> base url；測試結束關掉。"""
    started = []

    def start(www: Path) -> str:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(www)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"
    yield start
    for h in started:
        h.shutdown()
        h.server_close()


def open_page(edge, url, **ctx_kw):
    ctx = edge.new_context(viewport={"width": 390, "height": 844}, **ctx_kw)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    return ctx, page, errors


CC = {"credit": "某人", "license": "CC0", "url": "https://commons.wikimedia.org/wiki/File:A.jpg"}

# 一次涵蓋所有語法，外加一堆不該生效的東西（XSS）
MD = """# 大標題

第一段有 **粗體**、*斜體*、`行內 code`，還有[安全連結](https://example.com/a?x=1&y=2)和[電話](tel:+886212345678)。
同一段的第二行。

## 二級標題

### 三級標題

- 清單甲
- 清單乙 **粗**
* 星號清單

1. 第一步
2. 第二步

> 引言第一行
> 引言第二行

---

![內文圖](photo:甲)

![不存在的名稱](photo:nope)
![外部圖](https://evil.example/x.png)
![外部圖2](http://evil.example/y.png)

<script>window.__xss = 1</script>
<img src=x onerror="window.__xss = 2">
<b onmouseover="window.__xss = 3">不是粗體</b>
[壞連結](javascript:window.__xss=4)
[大寫壞連結](JaVaScRiPt:window.__xss=5)
[http 連結](http://example.com/plain)
[資料連結](data:text/html,<script>window.__xss=6</script>)
[mailto](mailto:a@example.com)
行內外部圖 ![圖](https://evil.example/z.png) 結束
"""


def _site(root: Path, *, article=None, resources=None):
    """root/src 放資料、root/www/site 是 build 輸出。回傳 (www, key)。"""
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "p.png").write_bytes(PNG)
    art = article or {
        "title": "示範文章", "subtitle": "副標", "date": "2026-11-05", "body": "前言 **粗**",
        "sections": [{"title": "第一段標題", "body": "內容一"}, {"title": "第二段標題", "body": "內容二"}],
        "photos": {"甲": {"file": "p.png", **CC}}, "cover": {"file": "p.png", **CC},
        "sources": [{"text": "來源甲", "url": "https://example.com/s"}], "changelog": [{"date": "11/05", "text": "建立"}]}
    res = resources or {
        "title": "示範清單", "subtitle": "副標", "intro": "簡介", "groups": [{"name": "工具", "icon": "link"}, {"name": "文章"}],
        "items": [
            {"title": "工具甲", "url": "https://example.com/a", "note": "說明甲", "tags": ["免費", "線上"], "group": "工具", "photo": {"file": "p.png", **CC}},
            {"title": "工具乙", "url": "https://example.org/b", "tags": ["付費"], "group": "工具"},
            {"title": "文章一", "url": "https://example.net/c", "tags": ["免費"], "group": "文章", "date": "2026-10-20"},
            {"title": "孤兒項目", "url": "https://example.com/d", "tags": ["線上"]}],
        "sources": [{"text": "來源乙", "url": "https://example.com/s2"}]}
    (src / "a.json").write_text(json.dumps(art, ensure_ascii=False), encoding="utf-8")
    (src / "r.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    site = {"title": "我們的分享", "you": "小安", "items": [
        {"slug": "art", "title": "示範文章", "template": "article", "data": "a.json"},
        {"slug": "res", "title": "示範清單", "template": "resources", "data": "r.json"}]}
    (src / "site.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    www = root / "www"
    key = build.build_site(src / "site.json", src / "key.txt", www / "site")
    return www, key


def _open(edge, server, tmp_path, slug, query="", **kw):
    www, key = _site(tmp_path, **kw)
    base = server(www)
    ctx, page, errors = open_page(edge, f"{base}/site/{slug}/{query}#k={build.b64u(key)}")
    page.wait_for_selector(".tabbar", timeout=10000)
    return ctx, page, errors, None


def _no_hscroll(page):
    return page.evaluate("() => document.documentElement.scrollWidth <= 390 && document.body.scrollWidth <= 390")


# ===== 文章 =====

def test_article_markdown_elements(tmp_path, edge, server):
    art = {"title": "T", "body": MD, "photos": {"甲": {"file": "p.png", **CC}}}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article=art)
    try:
        q = lambda sel: page.evaluate("(s) => document.querySelectorAll('#app ' + s).length", sel)
        txt = lambda sel: page.evaluate("(s) => [...document.querySelectorAll('#app ' + s)].map(e => e.textContent)", sel)
        assert txt(".md h2") == ["大標題"] and txt(".md h3") == ["二級標題"] and txt(".md h4") == ["三級標題"]   # # → h2（頁面的 h1 是標題列）
        assert q(".md ul > li") == 3 and txt(".md ul > li")[1] == "清單乙 粗"
        assert q(".md ol > li") == 2
        assert txt(".md blockquote.note p") and "引言第一行" in txt(".md blockquote.note")[0] and "引言第二行" in txt(".md blockquote.note")[0]
        assert q(".md p strong") >= 1 and txt(".md p strong")[0] == "粗體" and txt(".md p em") == ["斜體"] and txt(".md p code") == ["行內 code"]
        assert q(".md hr") == 1
        assert q(".md br") >= 1                                            # 同一段的換行保留
        # 連結：只有 https（新分頁、noopener noreferrer）和 tel
        links = page.evaluate("() => [...document.querySelectorAll('#app .md a')].filter(a => !a.closest('figcaption')).map(a => [a.textContent, a.getAttribute('href'), a.target, a.rel])")
        assert links == [["安全連結", "https://example.com/a?x=1&y=2", "_blank", "noopener noreferrer"], ["電話", "tel:+886212345678", "", ""]]
        # 圖：只有 photos 裡的名稱那一張（內文圖），而且是內嵌資料
        imgs = page.evaluate("() => [...document.querySelectorAll('#app img')].map(i => [i.getAttribute('src').slice(0, 22), i.alt])")
        assert imgs == [["data:image/png;base64,", "內文圖"]]
        assert "照片：" in page.text_content(".md-fig figcaption")
    finally:
        ctx.close()
    assert errors == []


def test_article_is_xss_safe(tmp_path, edge, server):
    art = {"title": "T", "body": MD, "photos": {"甲": {"file": "p.png", **CC}}}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article=art)
    try:
        page.wait_for_timeout(500)
        assert page.evaluate("() => window.__xss === undefined")           # <img onerror>、onmouseover 都沒生效
        # 資料裡的 HTML 是文字：#app 裡沒有任何 script、onerror／onmouseover 屬性、javascript:／data:／mailto: 連結
        assert page.evaluate("() => document.querySelectorAll('#app script, #app [onerror], #app [onmouseover], #app iframe, #app object, #app embed').length") == 0
        hrefs = page.evaluate("() => [...document.querySelectorAll('#app a')].map(a => a.getAttribute('href') || '')")
        assert not [h for h in hrefs if re.match(r"(?i)\s*(javascript|data|mailto|vbscript|http):", h)], hrefs
        assert page.evaluate("() => [...document.querySelectorAll('#app img')].every(i => i.src.startsWith('data:'))")
        body = page.text_content(".md")
        assert "<script>window.__xss = 1</script>" in body and '<img src=x onerror="window.__xss = 2">' in body   # 原樣當文字顯示
        assert "壞連結" in body and "大寫壞連結" in body and "http 連結" in body and "mailto" in body   # 連結文字還在，只是不能點
        for ev in ("click", "mouseover"):
            for el in page.query_selector_all("#app .md b, #app .md img[onerror]"):
                el.dispatch_event(ev)
        assert page.evaluate("() => window.__xss === undefined")
    finally:
        ctx.close()
    assert errors == []


def test_article_inline_image_and_forged_names(tmp_path, edge, server):
    """photos 名稱用 constructor／__proto__ 這種 Object 原型上的名字也不會誤判成有圖。"""
    art = {"title": "T", "body": "![a](photo:constructor) ![b](photo:__proto__) ![c](photo:toString) ![d](photo:甲) 尾", "photos": {"甲": {"file": "p.png", **CC}}}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article=art)
    try:
        assert page.evaluate("() => document.querySelectorAll('#app img').length") == 1
        assert page.evaluate("() => document.querySelector('#app img').classList.contains('md-inl')")
    finally:
        ctx.close()
    assert errors == []


def test_article_sections_switch_and_more(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art")
    try:
        labels = page.evaluate("() => [...document.querySelectorAll('.view:not([hidden]) .seg button')].map(b => b.textContent)")
        assert labels == ["前言", "第一段標題", "第二段標題"]              # 有 body 又有 sections：body 叫前言
        assert "前言" in page.text_content(".pane:not([hidden])")
        page.click('.seg button[data-sub="sec2"]')
        assert page.evaluate("() => document.querySelector('.pane:not([hidden]) .sec-h').textContent") == "第二段標題"
        assert "內容二" in page.text_content(".pane:not([hidden])") and page.get_attribute('.seg button[data-sub="sec2"]', "aria-selected") == "true"
        page.click('.tab[data-tab="more"]')
        assert page.is_visible("section.view[data-view=more]") and page.is_hidden("section.view[data-view=content]")
        more = page.text_content("section.view[data-view=more]")
        assert "來源甲" in more and "更新紀錄" in more and "建立" in more and "全部分享" in more
        assert page.get_attribute('section.view[data-view=more] a[href^="../#k="]', "href").startswith("../#k=")
        page.click('.tab[data-tab="content"]')
        assert page.evaluate("() => document.querySelector('.pane:not([hidden]) .sec-h').textContent") == "第二段標題"   # 回來停在上次那段
    finally:
        ctx.close()
    assert errors == []


def test_article_only_body_has_no_segments(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article={"title": "T", "body": "# 只有內文"})
    try:
        assert page.query_selector(".seg") is None and page.text_content(".md h2") == "只有內文"
        assert page.evaluate("() => document.querySelectorAll('.tab').length") == 2
    finally:
        ctx.close()
    assert errors == []


def test_article_view_param_opens_section(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", query="?view=sec2")
    try:
        assert page.evaluate("() => document.querySelector('.pane:not([hidden]) .sec-h').textContent") == "第二段標題"
        assert "view=" not in page.url
    finally:
        ctx.close()






def test_article_no_horizontal_scroll(tmp_path, edge, server):
    long = "超長網址 https://example.com/" + "a" * 200 + " 與一個很長很長的英文單字" + "x" * 150 + " `" + "c" * 150 + "`\n\n[" + "連" * 120 + "](https://example.com/z)"
    art = {"title": "標題很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長", "body": long,
           "sections": [{"title": "段" * 40, "body": long}, {"title": "乙", "body": "- " + long + "\n\n> " + long}],
           "photos": {"甲": {"file": "p.png", **CC}}, "sources": [{"text": "s" * 150, "url": "https://example.com/" + "p" * 150}]}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article=art)
    try:
        assert _no_hscroll(page)
        page.click('.seg button[data-sub="sec1"]')
        assert _no_hscroll(page)
        page.click('.seg button[data-sub="sec2"]')
        assert _no_hscroll(page)
        page.click('.tab[data-tab="more"]')
        assert _no_hscroll(page)
    finally:
        ctx.close()
    assert errors == []


# ===== 資源清單 =====

def test_resources_groups_and_links(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res")
    try:
        heads = page.evaluate("() => [...document.querySelectorAll('.grp-h')].map(h => h.querySelector('span:not([class])').textContent)")
        assert heads == ["工具", "文章", "其他"]                          # groups 設定的順序，沒 group 的歸「其他」放最後
        row = page.evaluate("() => [...document.querySelectorAll('a.rs-t')].map(a => [a.textContent, a.getAttribute('href'), a.target, a.rel])")
        assert row[0] == ["工具甲", "https://example.com/a", "_blank", "noopener noreferrer"] and len(row) == 4
        assert page.evaluate("() => [...document.querySelectorAll('.rs-host')].map(h => h.textContent)") == ["example.com", "example.org", "example.net", "example.com"]
        assert page.evaluate("() => document.querySelectorAll('.rs-img').length") == 1   # 只有工具甲有縮圖
        assert page.text_content(".rs-note") == "說明甲" and "示範清單" in page.text_content(".ab-title")
        assert "簡介" in page.text_content(".lead")
        assert page.evaluate("() => [...document.querySelectorAll('.seg.tagbar button')].map(b => b.textContent)") == ["全部", "免費", "線上", "付費"]
    finally:
        ctx.close()
    assert errors == []


def test_resources_tag_filter(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res")
    try:
        titles = lambda: page.evaluate("() => [...document.querySelectorAll('a.rs-t')].map(a => a.textContent)")
        page.click('.tagbar button[data-tag="1"]')                         # 免費
        assert titles() == ["工具甲", "文章一"] and page.get_attribute('.tagbar button[data-tag="1"]', "aria-pressed") == "true"
        assert page.evaluate("() => [...document.querySelectorAll('.grp-h')].length") == 2   # 沒有項目的群組不顯示
        page.click('.tagbar button[data-tag="3"]')                         # 付費：換掉，不是疊加
        assert titles() == ["工具乙"] and page.get_attribute('.tagbar button[data-tag="1"]', "aria-pressed") == "false"
        page.click('.tagbar button[data-tag="3"]')                         # 再點一次：回到全部
        assert len(titles()) == 4 and page.get_attribute('.tagbar button[data-tag="0"]', "aria-pressed") == "true"
        page.click('.tagbar button[data-tag="2"]')                         # 線上
        assert titles() == ["工具甲", "孤兒項目"]
        page.click('.tagbar button[data-tag="0"]')
        assert len(titles()) == 4
    finally:
        ctx.close()
    assert errors == []


def test_resources_empty_filter_and_more(tmp_path, edge, server):
    res = {"title": "T", "items": [{"title": "甲", "url": "https://example.com/a", "tags": ["x"]}], "changelog": [{"date": "11/05", "text": "建立"}]}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res", resources=res)
    try:
        page.click('.tab[data-tab="more"]')
        assert page.is_visible("section.view[data-view=more]") and "建立" in page.text_content("section.view[data-view=more]")
        page.click('.tab[data-tab="list"]')
        assert page.is_visible("a.rs-t")
    finally:
        ctx.close()
    assert errors == []


def test_resources_non_https_never_becomes_link(tmp_path, edge, server, monkeypatch):
    """build 驗證會擋，這裡繞過驗證，確認前端自己也再擋一次（硬性條件：url 只收 https）。"""
    monkeypatch.setitem(build.VALIDATORS, "resources", lambda d: [])
    res = {"title": "T", "items": [
        {"title": "http 項目", "url": "http://example.com/a"}, {"title": "js 項目", "url": "javascript:window.__xss=1"},
        {"title": "相對項目", "url": "//evil.example/x"}, {"title": "空網址", "url": ""}, {"title": "沒網址"},
        {"title": "<script>window.__xss=2</script>", "url": "https://example.com/ok", "note": "<img src=x onerror=\"window.__xss=3\">", "tags": ["<b>標</b>"]}],
        "sources": [{"text": "壞來源", "url": "javascript:window.__xss=4"}]}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res", resources=res)
    try:
        page.wait_for_timeout(400)
        hrefs = page.evaluate("() => [...document.querySelectorAll('#app a.rs-t')].map(a => a.getAttribute('href'))")
        assert hrefs == ["https://example.com/ok"]
        assert page.evaluate("() => document.querySelectorAll('span.rs-t').length") == 5   # 其餘 5 項只有標題文字，沒有連結
        assert page.evaluate("() => window.__xss === undefined")
        assert page.evaluate("() => document.querySelectorAll('#app script, #app [onerror], #app b').length") == 0
        assert "<script>window.__xss=2</script>" in page.text_content("#app")
        page.click('.tab[data-tab="more"]')
        assert page.evaluate("() => [...document.querySelectorAll('#app a')].every(a => !/^javascript:/i.test(a.getAttribute('href') || ''))")
    finally:
        ctx.close()
    assert errors == []




def test_resources_view_param(tmp_path, edge, server):
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res", query="?view=list-3")
    try:
        assert page.evaluate("() => [...document.querySelectorAll('a.rs-t')].map(a => a.textContent)") == ["工具乙"]
    finally:
        ctx.close()
    ctx, page, errors, _ = _open(edge, server, tmp_path / "b", "res", query="?view=more")
    try:
        assert page.is_visible("section.view[data-view=more]")
    finally:
        ctx.close()


def test_resources_no_horizontal_scroll(tmp_path, edge, server):
    res = {"title": "標題很長很長很長很長很長很長很長很長很長很長很長很長很長很長", "intro": "介" * 120,
           "groups": [{"name": "群組" * 20}],
           "items": [{"title": "項" * 60 + "y" * 100, "url": "https://example.com/" + "a" * 200, "note": "n" * 200, "group": "群組" * 20,
                      "tags": ["標籤" * 15, "t" * 60, "短"] + ["多%d" % i for i in range(20)], "photo": {"file": "p.png", **CC}}]}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res", resources=res)
    try:
        assert _no_hscroll(page)
        page.click('.tagbar button[data-tag="3"]')
        assert _no_hscroll(page)
        page.click('.tab[data-tab="more"]')
        assert _no_hscroll(page)
    finally:
        ctx.close()
    assert errors == []


# ===== 首頁：新種類的卡片 =====

def test_hub_cards_for_new_templates(tmp_path, edge, server):
    www, key = _site(tmp_path)
    base = server(www)
    ctx, page, errors = open_page(edge, f"{base}/site/#k={build.b64u(key)}")
    try:
        page.wait_for_selector(".icard", timeout=10000)
        cards = page.evaluate("() => [...document.querySelectorAll('.icard')].map(c => [c.querySelector('.ic-title').textContent, [...c.querySelectorAll('.ic-meta .chip')].map(x => x.textContent), !!c.querySelector('.ic-photo img'), !!c.querySelector('.ic-art svg')])")
        by = {c[0]: c for c in cards}
        assert "文章" in by["示範文章"][1] and "清單" in by["示範清單"][1]
        assert by["示範文章"][2] and by["示範清單"][2]                      # cover／第一張 photo 當封面
        assert page.evaluate("() => document.querySelector('.icard .ic-title').getAttribute('href')").startswith("./")
    finally:
        ctx.close()
    assert errors == []


# ===== QC 修正（2026-11-05） =====

def test_article_array_photos_load_nothing_external(tmp_path, edge, server, monkeypatch):
    """繞過 build 驗證，photos 寫成清單、src 是外部網址：build 拿掉 src，頁面不發外部請求、不出圖。"""
    monkeypatch.setitem(build.VALIDATORS, "article", lambda d: [])
    art = {"title": "T", "body": "![x](photo:0) ![y](photo:length)",
           "photos": [{"src": "https://evil.example/a.png", "credit": "x", "license": "x", "url": "https://a.com"}]}
    www, key = _site(tmp_path, article=art)
    base = server(www)
    ctx, page, errors = open_page(edge, f"{base}/site/art/#k={build.b64u(key)}")
    seen = []
    ctx.on("request", lambda r: seen.append(r.url))
    try:
        page.wait_for_selector(".tabbar", timeout=10000)
        page.reload()
        page.wait_for_selector(".tabbar", timeout=10000)
        page.wait_for_timeout(500)
        assert page.evaluate("() => document.querySelectorAll('#app img').length") == 0
        assert not [u for u in seen if "evil.example" in u]
    finally:
        ctx.close()
    assert errors == []


def test_icon_names_use_own_properties_only(tmp_path, edge, server):
    res = {"title": "T", "groups": [{"name": "甲", "icon": "constructor"}, {"name": "乙", "icon": "__proto__"}, {"name": "丙", "icon": "toString"}],
           "items": [{"title": "a", "url": "https://example.com/a", "group": g} for g in ("甲", "乙", "丙")]}
    ctx, page, errors, _ = _open(edge, server, tmp_path, "res", resources=res)
    try:
        html = page.evaluate("() => [...document.querySelectorAll('.g-ic')].map(e => e.innerHTML)")
        assert len(html) == 3 and all(h.startswith("<svg") and "function" not in h and "[object" not in h for h in html)   # 找不到的名稱一律用預設圖示
    finally:
        ctx.close()
    assert errors == []


def test_markdown_emphasis_is_linear_and_still_correct(tmp_path, edge, server):
    nasty = "**a " * 4000 + "\n\n" + "*b " * 4000 + "\n\n" + "**x ** y** **z**"
    art = {"title": "T", "body": nasty + "\n\n**粗** 與 *斜* 與 ***混***"}
    import time
    t0 = time.monotonic()
    ctx, page, errors, _ = _open(edge, server, tmp_path, "art", article=art)   # 含 build、載入、渲染
    try:
        assert time.monotonic() - t0 < 15
        assert page.evaluate("() => document.querySelectorAll('#app .md p').length") == 4
        last = page.evaluate("() => [...document.querySelectorAll('#app .md p')].pop().innerHTML")
        assert "<strong>粗</strong>" in last and "<em>斜</em>" in last
    finally:
        ctx.close()
    assert errors == []
