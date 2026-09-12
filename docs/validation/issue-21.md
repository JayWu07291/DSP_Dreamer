# Issue #21 正式實機驗收

2026-09-12，進行中。尚未通過本票品質 gate。#16、#17、#18、#20 的既有結果只作為前置證據，不取代本次長錄製。

## 適用版本

沿用 README 及前置票已確認的 `action_catalog_v3`／20 維與 `progress_version=3`。錄製仍為 20 Hz，模型視圖為 10 Hz。基準原始碼為 `2224d5bde219adbe9c474885a1eec440a50a5324`。

本次在 `frames.ndjson` 加入 capture 時點的 busy buffers、writer queue、event queue、pending readback 數，以及 readback 完成、writer 開始、encoder pipe 提交與 hash 完成的單調時間。這些欄位不更改觀測要求時間或模型輸入。`encoder_submitted_ticks` 不代表 encoder acknowledgement、檔案 flush 或持久化完成。佇列深度是每個成功 capture 的取樣，不宣稱捕捉到所有瞬時峰值。

callback 故障新增既有 schema 支援的 `gpu_readback_error`／`writer_backpressure` gap；scheduler 仍依 missed slots 計數，slot 不足為 `no_free_buffer`。readback 類別包含 readback callback 處理失敗，實際例外由遊戲日誌保留。

## 本次操作

1. 新 DLL 冷啟動後按 F6 產生候選指紋；核對二進位及設定後核准。再按 F6 完成約 18 秒探針，全程不操作、不切換視窗。正式 dataset 讀回及校正核准後，才開始人工錄製。
2. F8 開始工作階段，等基準自動載入。至少完成三次完整基準流程；每次成功後用 F9 重新載入同一基準，第三次完成後才 F8 發布。累計有效擷取跨度至少 1,800 秒，排除世界載入與成功後等待。若三次完成太快，須在成功前保留足夠遊玩或 UI 時間，不能把完成後停止擷取的等待算入。
3. 三次流程涵蓋主要 UI、游標、快速移動、建造與拆除。F9 重載需核對新 world binding 及進度事件。失焦／釋放另加一次短回合，避免將失焦後的無效回合當作完整成功。此處「重綁」先按世界重載後重新綁定事件驗證；輸入設定若變更，須重新核准指紋與校正。
4. 保存遊戲日誌、來源／四檔身分、版本、資源原始取樣及操作時點。容量不足停止新增錄製／編譯，保留舊 evidence 與失敗來源。

## 量測與核對

`tools/measure-recorder.ps1` 每 5 秒保存 UTC、實際經過時間、DSP／本 repo Python／固定 FFmpeg 的 PID、啟動時間、CPU、working set、private bytes、OS process peak，以及各磁碟可用 bytes。新錄製的 seal、evidence manifest、dataset 建立與 COMPLETED 狀態用來定位階段。階段邊界精度受取樣間隔限制；磁碟 free 差值也包含其他程序，不能直接宣稱是本工作獨占用量。

```powershell
.\tools\measure-recorder.ps1 -Out runs/issue21-resources-new.ndjson
# 建立同名 .stop 檔可停止取樣；Samples 可指定有限筆數作自我檢查。
.\tools\measure-recorder.ps1 -Out runs/issue21-check-new.ndjson -Samples 1
.\.venv\Scripts\python.exe tools/verify-recorder.py --evidence runs/live/ID.source.evidence --dataset runs/live/ID.source.dataset --ffmpeg E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe --out runs/issue21-audit-new.json
```

verifier 先使用正式四檔驗證器完整核對來源，再開啟模型視圖。額外逐幀解碼影片並比較 compiled RGB，逐窗讀取模型視圖，保存 Zarr chunk／shard、Parquet row groups、來源與 dataset checksum。RGB 逐幀處理；既有 loader 的事件、轉移及模型視窗 metadata 仍在 RAM，不能將此描述為所有資料均串流。

掉幀分母為成功幀加四類遺失 slots；scheduler 取 missed，其他 gap 每筆一 slot。有效寫入 Hz 使用各回合首末 capture 的時間差總和與成功幀間隔總數，排除回合間世界重載。此處「有效寫入」指成功保存的觀測，不等於模型可訓練視窗比例。原始 counters、ticks、frequency 與逐回合跨度均留在 JSON，不能只報百分比。

最終須分別列出錄製、合併、編譯的吞吐及 RAM／磁碟峰值，另計既有資料容量。`GiB/capture 小時` 使用本次實際檔案 bytes 與擷取跨度；未達 30 分鐘的探針不能校正正式長錄製容量。冷啟動、合併、恢復與清理，以及影片可播放仍須以本版新增結果逐項驗證。

## 目前證據

Release 建置 0 warnings／0 errors；封存與恢復專用 16 項測試通過；完整 pytest 137 項通過，170.77 秒，JUnit 在 `tmp/issue21-tests.xml`。mypy 包含新 verifier 共 17 檔通過。正式 C# SegmentWriter 的程序終止／恢復案例另核對新增提交時間為正且逐幀遞增，恢復後仍可編譯。

PowerShell 單筆取樣與真實 venv 子程序檢查通過，原始結果為 `runs/issue21-monitor-check-v3.ndjson`、`runs/issue21-monitor-python-check.ndjson`。後者核對 launcher 與實際 interpreter 兩個 PID 都有 working set，避免只量到 launcher。sampler 要求 PowerShell 7。

原有 27 份 evidence manifest 的 SHA-256、`runs/live` 原有總容量 73,893,112,235 bytes 與 E 槽可用量，保存於 `runs/issue21-existing-evidence.json`。部署備份在 `runs/issue21-deployment`。本次部署 DLL SHA-256 為 `9e03986148fc7d345e7318aa85843a0bcfda81c54305ad47b2fd69099794f1b3`，舊指紋核准已清空，新實機候選與校正尚待取得。

待填本次實機 artifact 與量測結果。未取得三個完整流程、30 分鐘原始資料及其完整核對前，不宣告本票通過。
