# fonts

build 會把這裡的字型縮成只含頁面用到的字（woff2），嵌進加密資料。用哪些字型由 `site.json` 的 `fonts` 決定（`hand`＝標題與小紙條、`num`＝數字與代碼）。

| 檔案 | 字型 | 授權 | 來源 |
|---|---|---|---|
| LXGWWenKaiTC-Medium.ttf | 霞鶩文楷 TC Medium | SIL OFL 1.1（`OFL_LXGWWenKaiTC.txt`） | https://github.com/lxgw/LxgwWenkaiTC（v1.530） |
| DMSerifDisplay-Regular.ttf | DM Serif Display | SIL OFL 1.1（`OFL_DMSerifDisplay.txt`） | https://github.com/google/fonts/tree/main/ofl/dmserifdisplay |

只放可以嵌入網頁的授權（例如 OFL）。換字型時把授權檔一起放進來。
