// share-hub 共用 JS。build.py 把模板 <script> 裡的 core.js 標記（PART 標記，見 README）換成這份內容。
// 前提：模板在標記前先宣告 PAYLOAD（payload 佔位那一行）、標記後自己宣告 let DATA／KEY_TEXT。
// 這裡不連外、不放跟內容有關的字串；內容一律用 el()／textContent 組，ICONS 是模板內寫死的 SVG，才可以用 innerHTML。
// 同一個站（第一層路徑）共用一把金鑰
const STORE = "sharekey:" + location.pathname.split("/").slice(0, 2).join("/");

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v; else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(String(k)));
  return n;
};
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const b64u = s => b64(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
const readJSON = k => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
const writeJSON = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };

// 離線可讀：註冊 service worker（同網域、只快取頁面），路徑由模板給（首頁 "./sw.js"、子頁 "../sw.js"）；沒網路時顯示提示
const registerSW = path => {
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register(new URL(path, location.href)).catch(() => {});
  }
};
function offlineBanner() {
  const old = document.querySelector(".offline");
  if (navigator.onLine) { old?.remove(); return; }
  if (!old) document.getElementById("app")?.prepend(el("div", { class: "offline", role: "status" }, "沒有網路，顯示的是上次打開的版本"));
}
addEventListener("online", offlineBanner);
addEventListener("offline", offlineBanner);

// 圖示：線條 SVG，跟著文字顏色。共用的基本集合在這裡，模板用 Object.assign(ICONS, {...}) 補自己的；找不到的名稱用 IC_FALLBACK（模板可改）
const svgIc = p => `<svg viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`;
const ICONS = {
  clock: svgIc('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
  info: svgIc('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.01"/>'),
  plane: svgIc('<path d="M10.5 20 13 13.5l5-1.5c1.4-.4 2-1.4 2-2.2s-.9-1.3-2.3-.9L13 10.3 7 4.5 5 5l3.6 6.6-3.8 1.1-2-1.6-1.3.4 1.6 3.4 3.6-.9L5.5 20.4z"/>'),
  doc: svgIc('<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 12h6M9 15.5h6"/>'),
  link: svgIc('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
  heart: svgIc('<path d="M12 20s-7-4.3-8.9-8.6C1.7 8.2 3.7 4.6 7.2 4.6c2 0 3.4 1.1 4.8 2.9 1.4-1.8 2.8-2.9 4.8-2.9 3.5 0 5.5 3.6 4.1 6.8C19 15.7 12 20 12 20z"/>'),
  chev: svgIc('<path d="m9.5 5 7 7-7 7"/>'),
  more: svgIc('<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>'),
  back: svgIc('<path d="m14.5 5-7 7 7 7"/>'),
  home: svgIc('<path d="M4 11 12 4l8 7v9H4z"/><path d="M10 20v-5h4v5"/>'),
};
let IC_FALLBACK = "";
const ic = (k, cls = "ic") => { const s = el("span", { class: cls, "aria-hidden": "true" }); s.innerHTML = (Object.prototype.hasOwnProperty.call(ICONS, k) && ICONS[k]) || (Object.prototype.hasOwnProperty.call(ICONS, IC_FALLBACK) && ICONS[IC_FALLBACK]) || ""; return s; };

// 下載到手機（PWA）：Android Chrome 跳安裝視窗；iPhone 給步驟；LINE 內建瀏覽器不能安裝，先換到外部瀏覽器（LINE 認 openExternalBrowser=1）
let INSTALL_EVT = null;
const IS_APP = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
addEventListener("beforeinstallprompt", e => { e.preventDefault(); INSTALL_EVT = e; document.querySelectorAll(".install").forEach(b => paintInstall(b)); });
addEventListener("appinstalled", () => document.querySelectorAll(".install").forEach(b => b.remove()));
function paintInstall(box) {
  const ua = navigator.userAgent, key = box.dataset.key || "", keep = box.dataset.keep === "1";
  const inLine = /\bLine\//i.test(ua), ios = /iPhone|iPad|iPod/.test(ua);
  let msg, act = null;
  if (inLine) {
    msg = "現在是在 LINE 裡面打開的，LINE 沒辦法下載。先換到瀏覽器打開，再按一次下載。";
    act = el("a", { class: "go", href: location.origin + location.pathname + "?openExternalBrowser=1" + (key ? "#k=" + key : "") }, "用瀏覽器打開");
  } else if (INSTALL_EVT) {
    msg = "下載後手機桌面會多一個「分享」圖示，點了直接打開，沒網路也看得到。";
    act = el("button", { class: "go", type: "button" }, "下載到手機");
    act.addEventListener("click", async () => { const e = INSTALL_EVT; INSTALL_EVT = null; e.prompt(); const r = await e.userChoice; if (r.outcome === "accepted") box.remove(); else paintInstall(box); });
  } else if (ios) {
    msg = "用 Safari 打開這一頁，點下方的「分享」按鈕，選「加入主畫面」。";
  } else {
    msg = "點 Chrome 右上角「⋮」，選「加到主畫面」或「安裝應用程式」。";
  }
  const x = keep ? null : el("button", { class: "x", type: "button", "aria-label": "先不要" }, "×");
  x?.addEventListener("click", () => { try { localStorage.setItem("install:hide", "1"); } catch (e) {} box.remove(); });
  box.replaceChildren(...[el("b", {}, "下載到手機"), el("p", {}, msg), act, x].filter(Boolean));
}
// keep：一直顯示（例如「說明」「更多」分頁），不給關閉鈕
function installCard(key, keep = false) {
  if (IS_APP) return null;
  if (!keep) { try { if (localStorage.getItem("install:hide")) return null; } catch (e) {} }
  const box = el("div", { class: "install", "data-key": key || "", "data-keep": keep ? "1" : "0" });
  paintInstall(box);
  return box;
}

const gate = (t, m) => document.getElementById("app").replaceChildren(el("div", { class: "gate" }, el("div", {}, el("b", {}, t), m)));

// 照片、字型都嵌在加密資料（build 放進 _photos／_fonts），頁面不從外部載
const photoSrc = ph => ph && (ph.src || (DATA._photos || [])[ph.ref]);
const ext = (href, cls, ...kids) => el("a", { class: cls, href, target: "_blank", rel: "noopener" }, ...kids);
const credit = (ph, cls) => ph ? el("small", { class: cls }, "照片：", ph.url ? ext(ph.url, null, ph.credit) : ph.credit, `，${ph.license}`) : null;
function loadFonts(f) {
  if (!f || !window.FontFace) return;
  const FAM = { hand: "TripHand", num: "TripNum" };
  for (const [k, data] of Object.entries(f)) {
    if (!FAM[k]) continue;
    try { const ff = new FontFace(FAM[k], b64(data).buffer, { display: "swap" }); document.fonts.add(ff); ff.load().catch(() => {}); } catch (e) {}
  }
}

function getKey() {
  const m = location.hash.match(/k=([A-Za-z0-9_-]+)/);
  if (m) { try { localStorage.setItem(STORE, m[1]); } catch (e) {} return m[1]; }
  try { return localStorage.getItem(STORE); } catch (e) { return null; }
}
async function decrypt(keyText) {
  const key = await crypto.subtle.importKey("raw", b64u(keyText), "AES-GCM", false, ["decrypt"]);
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(PAYLOAD.iv) }, key, b64(PAYLOAD.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
