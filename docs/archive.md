# 歷史資料封存

使用者要求將歷史測試內容封存搬離本機工作目錄，並明確要求單純搬運封裝，不進行逐包 SHA-256 或完整內容重讀。

目前封存工作仍在進行。**repo 已完成主要分類搬移，G 槽寫入與 Google Drive 同步尚未宣告完成；原件繼續保留。**

| 位置 | 用途 |
| --- | --- |
| `G:\我的雲端硬碟\DSP_Dreamer_Archive\2026-09-24-before-cleanup` | 45 個主要封存包、2 個暫存補充包及內容清單 |
| [Google Drive 封存資料夾](https://drive.google.com/drive/folders/1A6Fl6IRDOuen8wRIqsi4lWNm0m_U_OkD) | 雲端位置 |
| `E:\DSP_Dreamer_Archive_Staging\2026-09-24` | 同步完成前保留的全部歷史原件 |
| `data/maintenance/20260924/packing-status.json` | 封裝程序目前進度 |
| `data/maintenance/20260924/package-receipts/` | 已寫出的封存檔名稱、大小及包含的原路徑 |

盤點的邏輯檔案大小合計約 538.7 GiB，其中正式資料集約 158.5 GiB 保留在 `data/datasets/`，約 380 GiB 列入封存。這些是檔案長度加總，不是去除硬連結後的磁碟占用；尚未釋放的暫存空間不計為已回收。

## 封存內容

- `runs/live` 中的原始錄製、舊版及非正式資料集；24 份正式資料已先移到 `data/datasets/`。
- 其餘歷史 `runs`、部署備份、標註工作台、練習頁與人工原始提交。
- `docs/validation` 的歷次 JSON、Markdown、圖片、紀錄與一次性 Python 工具。
- 舊原型、反編譯參考碼、論文、外部參考 repo 與 VPT 範例資料。
- 測試暫存、舊建置產物及僅供 Issue #21 使用的 CI workflow。
- 整理前完整 Git bundle、原始碼快照，以及校正設定修改前後的副本。

保留現行產品程式、`tests/` 中持續使用的回歸測試、必要工具、凍結協定、領域決議與研究筆記。Git 歷史未改寫，整理前基準為 `0f3a9be`。Git 顯示歷史檔案從工作樹移除，對應原件仍在暫存及封存中。

## 封裝方式及還原

使用一般 7-Zip 封裝，`-mx=0` 不額外壓縮已編碼的錄影，也不重新編碼畫面。各包獨立，可按 `packages.json` 或各包的 `.json` 清單找到需要的內容；不必下載全部封存。

解壓後，`original-tree/` 下保留搬移前的相對路徑，例如 `original-tree/docs/validation/` 與 `original-tree/runs/live/`。還原到另一個資料夾即可查閱歷史內容。需要重現整理前環境時，先使用第一包 `administration/` 的 Git bundle 或原始碼快照，再還原所需資料；仍保留在本機的正式資料可依 `docs/data-catalog.json` 的 `previous_path` 對照原位置。

封裝只記錄工具是否成功寫出，不額外進行 archive test、逐包雜湊或重新讀取整批影片。檔案寫入 G 槽不等同 Google Drive 上傳完成，兩者分開記錄。

## 暫存補充包

第一包有 10 個 Windows 拒絕讀取的舊 `tmp/issue18-*` 測試目錄，已改由原本有讀取權限的程序封裝成 `046-protected-test-cache.7z`。原 `.pytest_cache` 已封裝成 `047-pytest-cache.7z`，兩包均已寫入 G 槽，沒有改動檔案權限。它們補足第一包收據所列的略過項目；需要時分別還原到 `tmp/` 及 `.pytest_cache/`。

原 `.pytest_cache` 已移出 repo 根目錄，暫存於 `data/maintenance/20260924/source-pytest-cache/`。其他原件仍在 repo 外暫存。同步完成前不移除暫存原件，不能將本頁視為 380 GiB 已經釋放的證明。
