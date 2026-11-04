"""share-hub：把要分享的資料（JSON）做成加密的分享站。

站的結構：首頁（清單）＋每個主題一頁（/<slug>/）。所有頁面用同一把金鑰加密，
金鑰只放在分享連結 `#k=` 後面（不會送到伺服器），對方只要存首頁那一個連結。

用法：
  python build.py --site private/site.json --key private/share_key.txt --out private/site [--base-url https://...]

- site.json：{"title", "intro", "items": [{"slug", "title", "date", "summary", "template", "data"}], "changelog": [...]}
  template 對應 templates/<template>.html，data 是該頁 JSON 的路徑（相對 site.json 或絕對路徑）。
- 金鑰檔不存在就自動產生；同一個站要一直用同一把，換了舊連結全部失效。
- 更新：改 JSON → 重跑本程式 → 推送輸出資料夾；對方重新整理就看到新版。
- 頁面不能加任何第三方 script（金鑰存在瀏覽器 localStorage，同網域的 script 讀得到）。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import shutil
import re
import secrets
from pathlib import Path, PureWindowsPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
PLACEHOLDER = "/*__PAYLOAD__*/null"
TZ = dt.timezone(dt.timedelta(hours=8))
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_or_create_key(path: Path) -> bytes:
    if path.exists():
        key = b64u_decode(path.read_text(encoding="utf-8").strip())
        if len(key) != 32:
            raise ValueError(f"金鑰長度不對：{path}")
        return key
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(b64u(key) + "\n", encoding="utf-8")
    return key


def encrypt(plaintext: bytes, key: bytes) -> dict:
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, plaintext, None)  # 密文＋16 bytes tag，跟 WebCrypto 格式相同
    return {"v": 1, "iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode()}


def decrypt(payload: dict, key: bytes) -> bytes:
    return AESGCM(key).decrypt(base64.b64decode(payload["iv"]), base64.b64decode(payload["ct"]), None)


def now_text(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(TZ)).strftime("%Y-%m-%d %H:%M")


def page_template(name: str) -> str:
    """讀模板（templates/<name>.html）。"""
    return (TEMPLATES / f"{name}.html").read_text(encoding="utf-8")


def render(data: dict, key: bytes, template: str) -> str:
    if PLACEHOLDER not in template:
        raise ValueError("模板找不到 payload 佔位字串")
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return template.replace(PLACEHOLDER, json.dumps(encrypt(plaintext, key)))


def resolve(base: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (base / path)


WEEK = "一二三四五六日"
DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})（(.)）")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})")
# 不該出現在分享頁的個資樣式（應急卡的公開電話除外）
PII = [(re.compile(r"\b[A-Z][12]\d{8}\b"), "身分證字號"),
       (re.compile(r"\b(?:09\d{2}[- ]?\d{3}[- ]?\d{3})\b"), "台灣手機號碼"),
       (re.compile(r"護照號碼|訂單編號|訂位代號|booking (?:no|number|id)", re.I), "訂單或護照號碼")]


def validate_trip(data: dict) -> list[str]:
    """渲染前的機械檢查。回傳錯誤清單（空的就是通過）。"""
    errs = []
    year = int(str(data.get("depart", "2000"))[:4]) if data.get("depart") else None
    for day in data.get("days", []):
        lab = day.get("label", "?")
        m = DATE_RE.search(day.get("date", ""))
        if year and m:
            try:
                wd = dt.date(year, int(m.group(1)), int(m.group(2))).weekday()
                if WEEK[wd] != m.group(3):
                    errs.append(f"{lab}：{day['date']} 的星期寫錯，應該是（{WEEK[wd]}）")
            except ValueError:
                errs.append(f"{lab}：日期不存在 {day.get('date')}")
        items = day.get("items", [])
        for it in items:
            leg = it.get("leg")
            if leg and isinstance(leg.get("from"), int) and 0 <= leg["from"] < len(items):
                ta, tb = TIME_RE.match(items[leg["from"]].get("time", "")), TIME_RE.match(it.get("time", ""))
                if ta and tb:
                    gap = (int(tb.group(1)) * 60 + int(tb.group(2))) - (int(ta.group(1)) * 60 + int(ta.group(2)))
                    if gap < leg.get("min", 0):
                        errs.append(f"{lab}：{items[leg['from']].get('title')} → {it.get('title')} 車程約 {leg['min']} 分，"
                                    f"但時間只隔 {gap} 分，排不下")
        last = -1
        for it in day.get("items", []):
            if not isinstance(it.get("photo"), dict):  # 2026-11-02 使用者要求：每個行程都一定要有照片
                errs.append(f"{lab}：{it.get('time', '')} {it.get('title', '')} 沒有照片（每個行程都要有圖）")
            if it.get("brand") and it["brand"] not in data.get("brands", {}):
                errs.append(f"{lab}：{it.get('title')} 的 brand「{it['brand']}」在 brands 裡找不到")
            t = TIME_RE.match(it.get("time", ""))
            if t:
                mins = int(t.group(1)) * 60 + int(t.group(2))
                if mins < last:
                    errs.append(f"{lab}：時間沒有照順序（{it['time']} {it.get('title', '')}）")
                last = mins
            if "map" in it and not str(it["map"]).strip():
                errs.append(f"{lab}：{it.get('title')} 的地圖關鍵字是空的")
    for c in data.get("checklist", []):
        if c.get("due"):
            try:
                dt.date.fromisoformat(c["due"])
            except ValueError:
                errs.append(f"清單截止日格式要 YYYY-MM-DD：{c['due']}")
    if "TODO" in json.dumps(data, ensure_ascii=False):
        errs.append("還有沒填完的 TODO（匯出的骨架要先補完）")
    public = dict(data)
    public.pop("emergency", None)
    text = json.dumps(public, ensure_ascii=False)
    for rx, what in PII:
        if rx.search(text):
            errs.append(f"疑似放了{what}：{rx.search(text).group(0)}")
    return errs


def validate_price_track(pt) -> list[str]:
    """價格追蹤檔的形狀檢查：series 每筆要有日期，金額要是數字或空值。"""
    if not isinstance(pt, dict):
        return ["價格追蹤檔要是物件"]
    errs = []
    series = pt.get("series")
    if not isinstance(series, list):
        return ["價格追蹤檔缺 series 清單"]
    for i, r in enumerate(series):
        if not isinstance(r, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(r.get("date", ""))):
            errs.append(f"價格追蹤第 {i + 1} 筆日期格式要 YYYY-MM-DD")
            continue
        for k in ("flight_total", "hotel_total", "total"):
            v = r.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                errs.append(f"價格追蹤 {r['date']} 的 {k} 要是數字或空值")
    return errs


# 資料裡會被 build 當成「相對頁面資料夾的路徑」去讀的鍵（file 另外在 inline_photos／inline_logos 處理）。
DATA_PATH_KEYS = ("file", "price_track_file")


def load_price_track(data: dict, data_dir: Path, warn=print) -> list[str]:
    """trip 資料有 price_track_file（相對資料檔）就讀進 data["price_track"]；檔案不在就警告、略過。
    每日更新只改這個獨立檔，不碰 trip.json。回傳檢查錯誤。"""
    ref = data.pop("price_track_file", None)
    data.pop("price_track", None)  # 不信任資料裡直接寫的
    if not ref:
        return []
    # 第二道防線：只讀頁面資料夾裡的檔，不收絕對路徑、磁碟代號、.. 跳出去
    w = PureWindowsPath(str(ref))
    path = resolve(data_dir, str(ref))
    try:
        inside = path.resolve().is_relative_to(Path(data_dir).resolve())
    except (OSError, RuntimeError, ValueError):
        inside = False
    if w.drive or w.root or str(ref).startswith(("/", "\\")) or not inside or chr(0) in str(ref):
        return ["價格追蹤檔（price_track_file）只能放在頁面資料夾裡，不能用絕對路徑或指到外面"]
    if not path.exists():
        warn(f"警告：價格追蹤檔不存在，略過：{path}")
        return []
    try:
        pt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        warn(f"警告：價格追蹤檔讀不了，略過：{path}（{e}）")
        return []
    errs = validate_price_track(pt)
    if not errs:
        data["price_track"] = pt
    return errs


VALIDATORS = {"trip": validate_trip}

SW_TEMPLATE = """// share-hub 離線快取：有網路時抓最新版，沒網路時用上次的版本。只快取同網域的頁面。
const CACHE = "share-hub-__STAMP__";
const PAGES = __PAGES__;
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PAGES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    const copy = res.clone();
    caches.open(CACHE).then(c => c.put(req, copy));
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true }).then(r => r || caches.match("./"))));
});
"""


PHOTO_MIME = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def strip_src(o) -> None:
    """photo／cover 物件的 src 一律拿掉、任何地方的 ref 一律拿掉。

    模板用 ph.src 或 _photos[ph.ref] 當圖片網址：src 是外部網址會從第三方載圖；ref 要由 build 自己指派，
    不能沿用資料裡的值（配上資料裡偽造的 _photos 一樣能載外部圖）。
    """
    if isinstance(o, dict):
        o.pop("ref", None)
        for k, v in o.items():
            if k in ("photo", "cover") and isinstance(v, dict):
                v.pop("src", None)
            strip_src(v)
    elif isinstance(o, list):
        for v in o:
            strip_src(v)


def drop_generated(data: dict) -> None:
    """資料裡 _ 開頭的頂層鍵（_photos、_logos、_fonts …）都是 build 產生的，不信任資料裡原本的值。"""
    for k in [k for k in data if isinstance(k, str) and k.startswith("_")]:
        del data[k]


def inline_photos(data: dict, base: Path) -> list[str]:
    """把資料裡所有 photo.file（相對於資料檔的圖檔）嵌進加密資料。

    頁面不能從別的網站載圖（離線可讀、不讓第三方知道行程），所以圖要嵌進加密資料。
    行程、機票卡、票券都可以放 photo；同一張圖只存一份：放進 data["_photos"]，photo 改記 ref（索引）。
    每張圖都要有 credit、license、url（CC 授權要求署名和出處）。回傳錯誤清單。
    """
    errs, found = [], []

    def walk(o, where):
        if isinstance(o, dict):
            if isinstance(o.get("photo"), dict):
                found.append((o["photo"], f"{where} {o.get('title') or o.get('name') or o.get('dir') or ''}".strip()))
            if isinstance(o.get("cover"), dict):  # 行程頁整趟封面（模板 tripCover 會讀 cover.ref）
                found.append((o["cover"], f"{where} 封面".strip()))
            for k, v in o.items():
                if k not in ("photo", "cover"):
                    walk(v, o.get("label", where) if k == "items" else where)
        elif isinstance(o, list):
            for v in o:
                walk(v, where)

    strip_src(data)
    data.pop("_photos", None)
    walk(data, "")
    pool: list[str] = []
    index: dict[str, int] = {}
    for ph, where in found:
        for k in ("credit", "license", "url"):
            if not ph.get(k):
                errs.append(f"{where} 的照片少了 {k}（要署名、授權、出處）")
        if "file" not in ph:
            errs.append(f"{where} 的照片要用本機檔（photo.file），不能連到外部網址")
            continue
        f = resolve(base, ph["file"])
        mime = PHOTO_MIME.get(f.suffix.lower())
        if not f.exists() or not mime:
            errs.append(f"{where} 的照片檔不存在或格式不支援：{ph['file']}")
            continue
        key = str(f.resolve())
        if key not in index:
            index[key] = len(pool)
            pool.append(f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode("ascii"))
        ph["ref"] = index[key]
        del ph["file"]
    if pool:
        data["_photos"] = pool
    return errs


LOGO_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp"}
SVG_BAD = re.compile(r"<script|\bon\w+\s*=|(?:href|src)\s*=\s*[\"'](?:https?:|//)|<foreignObject", re.I)


def inline_logos(data: dict, base: Path) -> list[str]:
    """把 brands[key].file（品牌 logo，相對資料檔）嵌進加密資料 data["_logos"][key]。

    跟照片一樣不從外部載；每個品牌要寫來源網址 url（商標只用來識別）。SVG 不能有 script、事件或外部連結。
    """
    errs, out = [], {}
    data.pop("_logos", None)
    for k, b in (data.get("brands") or {}).items():
        if not b.get("url"):
            errs.append(f"品牌 {k} 少了來源網址 url")
        f = resolve(base, b.get("file", ""))
        mime = LOGO_MIME.get(f.suffix.lower())
        if not b.get("file") or not f.is_file() or not mime:
            errs.append(f"品牌 {k} 的 logo 檔不存在或格式不支援（svg／png／webp）：{b.get('file')}")
            continue
        raw = f.read_bytes()
        if mime == "image/svg+xml" and SVG_BAD.search(raw.decode("utf-8", "ignore")):
            errs.append(f"品牌 {k} 的 SVG 有 script、事件或外部連結，不能用：{b['file']}")
            continue
        out[k] = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
        b.pop("file", None)
    if out:
        data["_logos"] = out
    return errs


FONT_SKIP_KEYS = {"_photos", "_fonts", "_logos", "photo", "geo", "route", "geo_map", "leg", "map", "link", "url", "currency"}


def page_text(data, extra: str = "") -> str:
    """頁面會顯示的所有文字（資料的字串值＋模板本身的字），用來決定字型要留哪些字。"""
    out = [extra]

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k not in FONT_SKIP_KEYS:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            out.append(o)

    walk(data)
    return "".join(out)


def embed_fonts(data: dict, fonts: dict, base: Path, text: str) -> list[str]:
    """把字型縮成只含這一頁用到的字（woff2），嵌進加密資料 data["_fonts"]。

    頁面不能從外部載字型；縮過的字型也看得出頁面用了哪些字，所以一樣放在加密資料裡。
    fonts：{"hand": 字型檔, "num": 字型檔}（相對 site.json）。只用可以嵌入的授權（例如 OFL）。
    """
    if not fonts:
        return []
    try:
        import io
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return ["要嵌字型得先裝 fonttools 和 brotli：pip install fonttools brotli"]
    errs, out = [], {}
    chars = "".join(sorted(set(text) | set("0123456789:/～-+.,，。、（）()% ")))
    for role, path in fonts.items():
        f = resolve(base, path)
        if not f.exists():
            errs.append(f"字型檔不存在：{path}")
            continue
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]
        opts.drop_tables += ["meta"]
        font = TTFont(str(f))
        sub = subset.Subsetter(opts)
        sub.populate(text=chars)
        sub.subset(font)
        font.flavor = "woff2"
        buf = io.BytesIO()
        font.save(buf)
        out[role] = base64.b64encode(buf.getvalue()).decode("ascii")
    if out:
        data["_fonts"] = out
    return errs


def content_version(item: dict, data: dict) -> str:
    """這一頁內容的版本號（不含每次 build 都會變的 updated）。首頁用它判斷「上次來之後有沒有更新」。"""
    meta = {k: item.get(k) for k in ("title", "date", "summary", "tag", "category")}
    raw = json.dumps([meta, data], ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def pick_cover(data: dict) -> dict | None:
    """一頁的封面照：資料的 cover 優先；行程頁照 trip 模板的挑法（標 cover → 標 star → 第一張）。"""
    if isinstance(data.get("cover"), dict):
        return data["cover"]
    cands = [it for day in data.get("days", []) for it in day.get("items", []) if isinstance(it.get("photo"), dict)]
    for pred in (lambda x: x.get("cover"), lambda x: x.get("star"), lambda x: True):
        for it in cands:
            if pred(it):
                return it["photo"]
    return None


def absolute_photo(photo: dict | None, base: Path) -> dict | None:
    """複製一份 photo，file 改成絕對路徑（首頁要用別頁的照片，相對路徑的基準不同）。"""
    if not photo:
        return None
    ph = dict(photo)
    ph.pop("src", None)
    ph.pop("ref", None)
    if "file" in ph:
        ph["file"] = str(resolve(base, ph["file"]).resolve())
    return ph


def build_site(site_path: Path, key_path: Path, out_dir: Path, now: dt.datetime | None = None) -> bytes:
    site = json.loads(site_path.read_text(encoding="utf-8"))
    key = load_or_create_key(key_path)
    stamp = now_text(now)
    out_dir.mkdir(parents=True, exist_ok=True)

    hub_items = []
    for item in site.get("items", []):
        slug = item["slug"]
        if not SLUG_RE.match(slug):
            raise ValueError(f"slug 只能用小寫英數和 -：{slug}")
        data_path = resolve(site_path.parent, item["data"])
        data = json.loads(data_path.read_text(encoding="utf-8"))
        drop_generated(data)
        ver = content_version(item, data)
        cover = absolute_photo(item["cover"], site_path.parent) if item.get("cover") else absolute_photo(pick_cover(data), data_path.parent)
        data["updated"] = stamp
        errs = []
        if item.get("template", "trip") == "trip":
            errs += load_price_track(data, data_path.parent)  # 在 ver 之後：每天的價格變動不要讓首頁標「新」
        errs += VALIDATORS.get(item.get("template", "trip"), lambda _: [])(data)
        errs += inline_photos(data, data_path.parent)
        errs += inline_logos(data, data_path.parent)
        tpl = page_template(item.get("template", "trip"))
        errs += embed_fonts(data, site.get("fonts", {}), site_path.parent, page_text(data, tpl))
        if errs:
            raise ValueError(f"{slug} 沒通過檢查：\n- " + "\n- ".join(errs))
        page_dir = out_dir / slug
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(render(data, key, tpl), encoding="utf-8")
        hub_item = {k: item.get(k) for k in ("slug", "title", "date", "summary", "tag", "category", "template")}
        hub_item.update(ver=ver, photo=cover)  # 用 photo 這個鍵，inline_photos 才會嵌進去
        hub_items.append({k: v for k, v in hub_item.items() if v is not None})

    prune_pages(out_dir, {h["slug"] for h in hub_items})

    # 首頁：分類、封面照、字型都跟各頁一樣嵌進加密資料
    hub = {"title": site.get("title", "分享"), "intro": site.get("intro", ""), "you": site.get("you", "你"),
           "categories": site.get("categories", []), "items": hub_items,
           "changelog": site.get("changelog", []), "updated": stamp}
    if site.get("cover"):
        hub["photo"] = absolute_photo(site["cover"], site_path.parent)
    hub_tpl = page_template("hub")
    errs = inline_photos(hub, site_path.parent)
    errs += embed_fonts(hub, site.get("fonts", {}), site_path.parent, page_text(hub, hub_tpl))
    if errs:
        raise ValueError("首頁沒通過檢查：\n- " + "\n- ".join(errs))
    (out_dir / "index.html").write_text(render(hub, key, hub_tpl), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    # PWA：manifest＋圖示（名稱用中性字，不洩漏內容）
    icon_dir = out_dir / "icons"
    icon_dir.mkdir(exist_ok=True)
    for f in (TEMPLATES / "icons").glob("*.png"):
        shutil.copyfile(f, icon_dir / f.name)
    manifest = {"name": site.get("app_name", "分享"), "short_name": site.get("app_name", "分享"), "lang": "zh-Hant",
                "start_url": "./", "scope": "./", "display": "standalone",
                "background_color": "#fbf6ef", "theme_color": "#fbf6ef",
                "icons": [{"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                          {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                          {"src": "icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    (out_dir / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    pages = ["./", "./manifest.webmanifest", "./icons/icon-192.png"] + [f"./{h['slug']}/" for h in hub_items]
    sw = SW_TEMPLATE.replace("__STAMP__", stamp.replace(" ", "T")).replace("__PAGES__", json.dumps(pages))
    (out_dir / "sw.js").write_text(sw, encoding="utf-8")
    return key


def prune_pages(out_dir: Path, slugs: set[str]) -> None:
    """輸出資料夾裡已經不在 items 的頁刪掉；push 是 git add -A，不刪的話拿掉的頁會一直留在線上。

    兩道保險（--out 打錯，例如指到 private，不能刪到正本）：
    - out_dir 要已經是 build 輸出過的資料夾（根目錄有上次 build 寫的 sw.js 和 manifest.webmanifest）；
    - 只刪「裡面只有 index.html」的資料夾（build 產生的頁就只有這一個檔），名字要像 slug、不是連結；icons 不動。
    """
    if not ((out_dir / "sw.js").is_file() and (out_dir / "manifest.webmanifest").is_file()):
        return
    keep = set(slugs) | {"icons"}
    for d in out_dir.iterdir():
        if d.name in keep or not SLUG_RE.match(d.name) or d.is_symlink() or d.is_junction() or not d.is_dir():
            continue
        kids = list(d.iterdir())
        if len(kids) == 1 and kids[0].name == "index.html" and kids[0].is_file() and not kids[0].is_symlink():
            kids[0].unlink()
            d.rmdir()


def push(out_dir: Path) -> None:
    import subprocess

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(out_dir), *a], capture_output=True, text=True, encoding="utf-8")

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        raise SystemExit(f"{out_dir} 不是 git repo，先照 README 建 repo")
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("內容沒有變，不用推送")
        return
    r = git("commit", "-q", "-m", "update")  # 作者用輸出 repo 自己的 git 設定
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    r = git("push", "-q")
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    print("已推送；GitHub Pages 大約 1～2 分鐘後更新")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, type=Path)
    ap.add_argument("--key", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--push", action="store_true", help="輸出資料夾是 git repo 時，commit（訊息固定 update）並推送")
    args = ap.parse_args()
    key = build_site(args.site, args.key, args.out)
    print(f"已輸出：{args.out}")
    if args.push:
        push(args.out)
    if args.base_url:
        print(f"分享連結：{args.base_url.rstrip('/')}/#k={b64u(key)}")
    else:
        print(f"本機預覽：{(args.out / 'index.html').resolve().as_uri()}#k={b64u(key)}")


if __name__ == "__main__":
    main()
