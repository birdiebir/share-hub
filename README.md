# share-hub-template

一個**加密的多頁靜態分享站產生器**：把要分享給某個人的內容（JSON）用 AES-256-GCM 加密成一組靜態頁面，丟到 GitHub Pages 或任何靜態主機就能用。**金鑰只放在分享連結 `#k=` 後面**，不會送到伺服器；沒有連結的人只看到「需要分享連結」。

- 一把金鑰管整個站（首頁清單＋每個主題一頁），對方存一個連結就好，之後新增、修改的內容重新整理就看到。
- 手機優先、App 式分頁、淺色／深色自動切換、離線可讀（PWA）、頁面零第三方 script。
- 程式跟個人資料分開：站的設定、內容和金鑰放 `private/`（不進 git）。

## 安全模型與限制

- **加密**：AES-256-GCM，Web Crypto 在瀏覽器解密。金鑰在網址 `#k=` 片段，解過一次後存在瀏覽器 localStorage（子頁、從主畫面打開才不用再帶）。
- **誰能看**：拿到連結的人就能看，也能轉傳；要讓舊連結失效就換金鑰重跑（輸出全部重新加密）。
- **同網域限制**：localStorage 以網域為界。GitHub Pages 同一個帳號的所有專案頁是同一個網域，同網域的**其他頁面的 script 讀得到金鑰**。所以建議用**獨立網域，或專門放這個站的獨立 GitHub 帳號／組織**的 Pages，不要跟其他有 script 的網站混在同一個網域。本站自己的頁面不載任何第三方 script（有測試把關）。
- 輸出的 HTML 檔名與資料夾名（slug）是明文，不要把敏感內容寫進 slug；標題、內文、照片、字型子集都在加密資料裡。
- 不要放護照號碼、訂單號、電話這類資料（build 會對部分樣式擋下來）。
- 這是個人分享用工具，沒有帳號系統、沒有稽核，也沒有經過第三方資安審查。

## 快速開始：用 private.example 跑起來

需求：Python 3.11+、`pip install cryptography fonttools brotli pillow pytest`（依 build.py 實際匯入為準）。

```
python build.py --site private.example/site.json --key private/share_key.txt --out out-example
```

- 會在 `out-example/` 產生加密站，終端機印出本機預覽網址（含 `#k=`），用瀏覽器開啟即可。
- `private.example/` 是虛構範例（`site.json` 設定、`trip.json` 範例行程、`article.json` 範例文章、`resources.json` 範例資源清單、`photos/` 與 `img/` 程式產生的插圖）。自己用時複製成 `private/` 再改；金鑰檔不存在會自動產生，**同一個站一直用同一把**。

## 用法

```
python build.py --site private/site.json --key private/share_key.txt --out private/site [--base-url https://<帳號>.github.io/<repo>]
```

- `private/site.json`：`title`、`intro`、`items[]`（`slug`、`title`、`date`、`summary`、`tag`、`template`、`data`）、`changelog[]`。範本見 `private.example/site.json`。
  - 首頁另外讀：`you`（稱呼對方，預設「你」）、`cover`（首頁封面照，photo 物件，相對 site.json；沒有就用漸層＋海浪）、`categories`（`[{name, icon}]`，分類順序和沒照片時的圖示）、`items[].category`（沒有就用 `tag`）、`items[].cover`（卡片照片；沒有就從那一頁挑，挑法同行程頁封面）。
  - 首頁是 App 式三個分頁：**分享**（封面、統計卡、分類段落與項目卡片；分類有兩類以上才出現上方分段）、**更新**（更新紀錄）、**說明**（下載到手機、怎麼用）。
  - 「新」：build 幫每份分享算版本號（內容雜湊，不含 `updated`），首頁跟對方手機裡記的版本比，不同就標「新」，點進去就消掉；第一次打開全部當看過。更新紀錄有新的一筆時，「更新」分頁亮紅點。
- `templates/<template>.html`：目前有 `hub`（首頁）、`trip`（行程）、`article`（文章）、`resources`（資源清單）。新類型的內容就加一個模板；欄位與做法見下面「模板清單」。
- 金鑰檔不存在會自動產生；**同一個站一直用同一把**，換了舊連結全部失效。
- 輸出資料夾推到 GitHub Pages（或任何靜態主機）。commit 訊息寫中性的 `update`。
- 測試：`python -m pytest -q`（`test_build.py` 是單元測試；`test_templates_ui.py` 用 Playwright＋Microsoft Edge 做瀏覽器測試，沒裝就自動跳過）

## 發布與更新

- 發布設定可記在 `private/publish.json`（repo 名稱、網址，自訂格式，程式不讀）。輸出資料夾 `private/site` 本身就是那個 repo 的工作目錄，只含加密後的檔案。
- **日常更新**（改了某頁的 JSON 或 site.json 之後）：
  ```
  python build.py --site private/site.json --key private/share_key.txt --out private/site --base-url <publish.json 的 base_url> --push
  ```
  `--push` 會用固定訊息 `update` commit 並推送，Pages 約 1～2 分鐘後更新，對方重新整理就看到。
- 拿掉某一頁：從 site.json 刪掉，然後照上面更新。build 會自動刪掉輸出資料夾裡不在 items 的頁（像 slug 的資料夾；`icons`、`.git` 不動）。
- 照片、cover 的 `src`（外部網址）build 一律拿掉，頁面不會從第三方載圖。
- 第一次建站（換新站才需要）：`git init -b main` → `gh repo create <帳號>/<沒有意義的名稱> --public --source=. --push`（不填描述）→ `gh api -X POST repos/<帳號>/<repo>/pages -f "source[branch]=main" -f "source[path]=/"`。

## 模板清單

| 模板 | 用途 | 分頁 |
|---|---|---|
| `hub` | 首頁：分類、項目卡片、更新紀錄、說明 | 分享／更新／說明 |
| `trip` | 行程 | 行程／預訂／行李／更多 |
| `article` | 文章（Markdown 內文） | 內容（有 `sections` 時上方多一排分段）／更多 |
| `resources` | 資源清單（連結＋標籤篩選） | 清單／更多 |

首頁卡片：`article` 圖示 `doc`、小標「文章」；`resources` 圖示 `link`、小標「清單」；行程不加小標。沒有 `cover` 時，文章用 `photos` 第一張、清單用第一個有 `photo` 的項目，都沒有就用分類圖示。

### article 欄位

`title`（必填）、`subtitle`、`date`（顯示用的文字）、`cover`（photo）、`body`（Markdown 字串）、`sections[]`（`{title, body}`）、`photos`（`{名稱: photo}`）、`sources[]`（`{text, url}`，url 只收 https）、`changelog[]`（`{date, text}`）。`body` 和 `sections` 至少要有一個；兩個都有時，`body` 在分段裡叫「前言」。每張 photo 要有 `file`（本機檔，相對資料檔）、`credit`、`license`、`url`，build 嵌進加密資料。

Markdown 子集（頁面 JS 自己解析，用 DOM 組，不用 innerHTML）：`#`／`##`／`###`（變成 h2／h3／h4，頁面的 h1 是標題列）、段落（空行分段，同一段的換行保留）、`-`／`*`／`1.` 清單（一層）、`> ` 引言（小紙條）、`**粗**`、`*斜*`、`` `code` ``、`[文字](https://…)`／`[文字](tel:…)`（其他協定只留文字；https 連結新分頁開、`noopener noreferrer`）、`![說明](photo:名稱)`（只認 `photos` 裡的名稱；外部網址、不存在的名稱都不顯示）、`---` 分隔線。原始 HTML 一律當文字顯示。

### resources 欄位

`title`（必填）、`subtitle`、`intro`、`cover`、`groups[]`（`{name, icon}`，卡片順序和圖示；圖示名稱用 core.js／模板有的，找不到用 link）、`items[]`（`{title, url, note, tags[], group, photo, date}`；`title`、`url` 必填，`url` 只收 https，build 擋一次、前端再擋一次）、`sources[]`、`changelog[]`。清單分頁上方是標籤篩選列（「全部」＋各標籤，單選，再點一次取消），下面依 `group` 分卡片（沒有 group 歸「其他」放最後）。

### 共用層（partials）與 PART 標記

- `templates/partials/base.css`（token、reset、App 殼的標題列／分段／分頁列、卡片、安裝卡、離線條、空狀態、gate、skeleton、mobile-native）和 `core.js`（`el`、base64、readJSON／writeJSON、`registerSW(路徑)`、離線條、ICONS 基本集合與 `ic()`、安裝卡、`gate`、`photoSrc`／`ext`／`credit`、`loadFonts`、`getKey`、`decrypt`）。
- 模板在 `<style>` 最前面寫 `/*__PART:base.css__*/`、在 `<script>` 裡 `const PAYLOAD` 後面寫 `/*__PART:core.js__*/`；`build.page_template()` 在算字型子集之前換成片段內容（找不到片段檔就報錯；同一標記出現幾次換幾次；片段裡的註解輸出時去掉）。模板自己的規則寫在後面，覆蓋共用的值。
- 模板在標記後自己宣告 `let DATA`、`let KEY_TEXT`，用 `Object.assign(ICONS, {...})` 補自己的圖示，`IC_FALLBACK` 可改找不到圖示時的預設。

## trip 模板欄位

`title`、`subtitle`、`status[]`（label／state／ok）、`picks`（title、nav、items[]：name／where／done）、`days[]`（label、short、title、date、summary、tip、items[]：time／title／note／map／link／star／optional）、`transport`（rows[[k,v]]，航班與當地交通）、`hotel`（rows[[k,v]]、map）、`budget`（title、rows[]：item／note／amount、totalLabel、total、fine[]）、`checklist[]`（text／who／done）、`packing[]`、`notes[]`、`changelog[]`、`footer`，以及 `depart`／`return`（YYYY-MM-DD，出發倒數）、`checklist[].due`（YYYY-MM-DD）、`days[].rain`（雨天備案）、`emergency`（address：label／name／text／map；calls[]：label／number／display／note；notes[]）、`sources[]`（text／url）。`updated` 由 build.py 自動填。

## 渲染前檢查與離線

- 先把資料統整進 JSON，再渲染：`build.py` 會先跑 `validate_trip`，日期星期、時間順序、截止日格式、個資樣式（應急卡的公開電話除外）沒過就停下來。
- build 同時產生 `sw.js`，頁面打開過一次之後沒網路也能看（只快取同網域頁面）。
- 行程頁的清單打勾和每天的「我的筆記」只存在瀏覽者自己的手機（localStorage），不會傳回來；換手機或清除瀏覽資料就會不見。
- 照片：任何地方（行程項目、機票卡、票券）都可以加 `photo`（`file` 相對於資料檔、`alt`、`credit`、`license`、`url`）。build 把圖嵌進加密資料（同一張圖只存一份，放在 `_photos`，photo 記 `ref`），頁面不從外部載圖；少了署名、授權、出處，或指到外部網址，build 會擋下來。圖先縮到 720 px 寬的 WebP（每張約 10～45 KB）。
- 行程頁是 App 式分頁畫面，不是長網頁：底部四個分頁，每個分頁上方有標題列和分段切換，一次只顯示一個子畫面；手機返回鍵可以回上一個畫面；打字時底部分頁收起來。
  - **行程**：總覽（封面、倒數、想去的、每日卡）＋ Day 1～N；旅途中打開直接到今天。
  - **預訂**：機票（`transport.flights[]`：dir、date、airline、no、from／to 的 code、name、time，duration、note、photo，畫成登機證卡；`transport.rows` 去掉去程／回程後當「訂票資訊」）、住宿（`hotel.card`：name、area、checkin／checkout 的 date、time，nights；小地圖用 `hotel.geo`＋島的輪廓畫；`hotel.rows` 當「訂房資訊」）、其他（`transport.local_rows`、`tickets[]`：name、when、price、note、status、photo）。
  - **行李**：上方一張進度卡（完成幾項、最近要做的事），下面每一類一張卡，類別標題顯示「完成／總數」。清單項目的文字用第一個「：」拆成標題和說明。
    - 出發前要做（`checklist`）：每項加 `group`，類別順序和圖示寫在 `checklist_groups`（`[{name, icon}]`）；沒有 group 的照截止日自動分（過期了／這週要做／這個月／之後）。改 `text` 前先加 `key`＝原文，手機上的打勾才不會掉。
    - 打包清單（`packing`）：可以是字串，或 `{group, icon, items: [字串]}`；打勾的 key 是 `pack:`＋文字。`luggage`（`[[項目, 說明]]`）放在最後當「行李規定」。
    - 類別圖示可用：ticket、id、clock、sun、beach、shirt、luggage、plane、hotel、money、info 等（模板的 `ICONS`）。
  - **更多**：換算、應急、預算、小提醒、資料來源、更新紀錄、全部分享。
  - **每個行程項目都要有 `photo`**（build 會擋）。品牌 logo：`brands`（`{key: {name, file, url, license}}`，file 相對資料檔，svg／png／webp，build 嵌進 `_logos`），在行程項目、`transport.flights[]`、`tickets[]`、`hotel.card` 加 `brand: key`；「想去的」`picks.items[].photo` 會顯示成照片卡。
  - 行程項目沒照片時用 `icon` 顯示插圖小方塊（舊資料相容用）（work、hotel、breakfast、car、meal、night、spa、beach、sunset、luggage、shop）。沒有新欄位的舊資料照樣能顯示，只是少了卡片。
- 字型：`site.json` 加 `"fonts": {"hand": 字型檔, "num": 字型檔}`（相對 site.json），build 會用 fonttools 縮成只含這一頁用到的字（資料的字串＋模板本身的字），存成 woff2 嵌進加密資料（`_fonts`），頁面用 FontFace 掛上。縮過的字型看得出用了哪些字，所以一樣要加密。預設用 `fonts\` 裡的霞鶩文楷 TC（標題、小紙條）和 DM Serif Display（數字、機場代碼），都是 OFL；沒設定就用系統字。加了字型後一頁約 1 MB 多。
- 行程頁的版面：總覽是滿版封面照＋手寫標題，倒數卡浮在封面下緣，接著是準備進度、想去的、每一天（橫滑照片卡）。每天的畫面是封面照、導言、小紙條（`tip`）、時間軸卡片（有照片的卡片上方放照片），路線圖放在最後。封面照挑法：行程項目標 `cover: true` 的優先，其次是 `star`，再其次是第一張照片；整趟的封面也可以直接給 `cover`（photo 物件）。
- 首頁和行程頁頁首有「下載到手機」卡片（Android 跳安裝視窗、iPhone 給步驟、LINE 內建瀏覽器先換到外部瀏覽器）；用 App 打開或按過 × 就不顯示。
- PWA：build 會輸出 `manifest.webmanifest` 和 `icons/`（圖示在 `templates/icons/`），可以「加到主畫面」當 App 開，名稱用中性字（`site.json` 的 `app_name`，預設「分享」）。從主畫面打開時網址沒有 `#k=`，靠 localStorage 裡的金鑰解密。
- trip 模板額外讀這些欄位（可由自己的行程產生工具填入）：
  - 項目的 `geo`、`leg`：每段車程、編號。
  - 每天的 `route` 和 `geo_map.outline`：每日路線圖（SVG），加上「整天路線在 Google Maps 打開」。
  - `currency`：換算段。
- 旅途中打開，頁首顯示「下一站、還有幾分、導航過去」，每分鐘更新。網址加 `?now=2026-12-05T16:25` 可以模擬時間，截圖測試用。
- 渲染前的檢查另外會擋兩種情況：還有 TODO（export 骨架沒補完）；前一站到下一站的時間比車程短（排不下）。

## 個資掃描（選用）

- `guard/scan.py` 在 commit／push 前擋下人名、email、個人路徑：先把 `private.example/blocklist.txt` 複製成 `private/blocklist.txt` 改成自己的名單，再跑 `python guard/install_git_hooks.py` 裝 pre-commit（掃暫存區）與 pre-push（掃全部歷史）。
- 允許清單寫死了原作者的 GitHub 帳號（noreply 信箱、`github.com/<帳號>`）；fork 後改成自己的帳號（`guard/scan.py` 的 `_HANDLE`）。

## 規則

- **頁面不能加任何第三方 script**：金鑰存在瀏覽器 localStorage，GitHub Pages 同一個帳號的網站是同網域，外部 script 讀得到（有測試把關）。
- 模板裡不要寫跟內容有關的明文（名字、地點），一律放進加密的 JSON。
- 拿到連結的人就能看，也能轉傳；要讓舊連結失效就換金鑰重跑。
- 不要放護照號碼、訂單號、電話這類資料。

## Licenses

- 程式：MIT（見 `LICENSE`）。
- 字型（打包在 `fonts/`，build 時縮成子集嵌進頁面；兩款都是 SIL Open Font License 1.1，允許再散布與嵌入，授權全文在同資料夾）：
  - 霞鶩文楷 TC Medium（LXGW WenKai TC）：OFL 1.1，https://github.com/lxgw/LxgwWenkaiTC
  - DM Serif Display Regular：OFL 1.1，https://github.com/google/fonts/tree/main/ofl/dmserifdisplay
  - 想換字型：放進 `fonts/` 並在 `site.json` 的 `fonts` 指定，只用允許嵌入網頁與再散布的授權，授權檔一起放。
- `templates/icons/` 的 PWA 圖示與 `private.example/photos/placeholder.webp`：本專案自製，隨本專案以 MIT 授權（圖示作者為專案作者，請 fork 者自行確認）。
- 使用者自己放進 `photos` 的圖，build 會要求填 `credit`、`license`、`url`，授權由使用者負責。
