# Issue #21 正式實機驗收

更新至 2026-09-13，進行中。首輪五次流程達到 30 分鐘，但掉幀率超標，尚未通過本票品質 gate。#16、#17、#18、#20 的既有結果只作為前置證據，不取代本次長錄製。

## 適用版本

沿用 README 及前置票已確認的 `action_catalog_v3`／20 維與 `progress_version=3`。錄製仍為 20 Hz，模型視圖為 10 Hz。基準原始碼為 `2224d5bde219adbe9c474885a1eec440a50a5324`。

本次在 `frames.ndjson` 加入 capture 時點的 busy buffers、writer queue、event queue、pending readback 數，以及 readback 完成、writer 開始、encoder pipe 提交與 hash 完成的單調時間。這些欄位不更改觀測要求時間或模型輸入。`encoder_submitted_ticks` 不代表 encoder acknowledgement、檔案 flush 或持久化完成。佇列深度是每個成功 capture 的取樣，不宣稱捕捉到所有瞬時峰值。

callback 故障新增既有 schema 支援的 `gpu_readback_error`／`writer_backpressure` gap；scheduler 仍依 missed slots 計數，slot 不足為 `no_free_buffer`。readback 類別包含 readback callback 處理失敗，實際例外由遊戲日誌保留。

## 本次操作

1. 新 DLL 冷啟動後按 F6 產生候選指紋；核對二進位及設定後核准。再按 F6 完成約 18 秒探針，全程不操作、不切換視窗。正式 dataset 讀回及校正核准後，才開始人工錄製。
2. F8 開始工作階段，等基準自動載入。以自然速度完成至少三次完整基準流程，每次成功後用 F9 重新載入同一基準；累計擷取跨度至少 1,800 秒後才 F8 發布，排除世界載入與成功後等待。使用者每回合約六至八分鐘，已改為增加完整流程次數，不要求刻意等待；本輪實際錄製五次。
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

原有 27 份 evidence manifest 的 SHA-256、`runs/live` 原有總容量 73,893,112,235 bytes 與 E 槽可用量，保存於 `runs/issue21-existing-evidence.json`。部署備份在 `runs/issue21-deployment`。初次量測 DLL 的 SHA-256 為 `9e03986148fc7d345e7318aa85843a0bcfda81c54305ad47b2fd69099794f1b3`；審查後補齊 callback 前例外的 gap，部署改為 `8d57b61ae1265c42568262b43ffc99426885060771f206cfc4331bb55fb4abfd`，前版另存 `telemetry-initial.dll`。舊指紋核准已清空，新實機候選與校正尚待取得。

以下保留初次準備與校正紀錄；2026-09-13 長錄製與修復結果見末節。

## Standards

獨立審查未發現 AGENTS.md／domain 規範違反。取樣會漏掉瞬時峰值的限制已補上 `ponytail:` 註解與升級方向。單一 verifier 同時核對及產生本票報告，審查認為作為一次性驗收工具可接受，不拆出額外架構。

## Spec

獨立審查發現一項掉幀漏計：CaptureLoop 外層例外會丟棄 slot，但沒有 gap。已在 EndEpisode 前補上 `gpu_readback_error`，尚無 capture ID 時保留 null；正式 schema 允許此欄位，verifier 依 gap 計數而不依賴 capture ID。原審查者複核確認已解決。修正後 Release 建置及封存／診斷 24 項測試通過。這不代表已執行對應自然 GPU 故障的實機測試。

修正後最終完整 pytest 137 項通過，167.63 秒，JUnit 在 `tmp/issue21-tests-final.xml`。

Standards 1 項註解缺口已處理，Spec 1 項掉幀漏計已修正；沒有未解決的準備程式 finding。

## 新版冷啟動與校正

2026-09-12，使用者冷啟動 DSP 並執行 F6。候選指紋 `65aacc586235f804a556e4a7b09c52c15a94124fbd5b8c50796c97c5f6874245` 已逐一核對 11 個磁碟二進位／遊戲資源雜湊及目前 options.xml；除新版 DLL 外，runtime 設定與 #20 已通過的重啟證據一致。候選原檔保存於 `runs/issue21-runtime-20260912.json`。

新版 F6 錄製為 `ded6443d-93b9-44d0-8097-0717f34e2f58`。正式 compiler 發布 406 筆轉移，控制 verifier 通過，44 個模型要求全部有實際觀察，NumPad1 讀為 End 並與 Digit1 區分；詳細要求、釋放與 sample refs 見[校正報告](issue-21-calibration-live.json)。已發布並核准 `runs/issue21-ded6443d-calibration.json`，SHA-256 為 `c97d86595e049ece90ecba4537fd7c96083da4c49f521bf9199778a3ca796dcf`，Diagnostics 保持 false。

新錄製 verifier 已實際跑通：407 幀完整 RGBA 驗證、逐幀 compiled RGB 比較及 203 個模型視窗讀回通過。擷取跨度 20.3917211 秒，scheduler 遺失 2 slots，分母 409，掉幀率 0.488998%；成功寫入間隔 406，寫入率 19.9100408 Hz。GPU readback error、slot 不足及 writer backpressure 均為 0。writer queue 取樣最高 6、busy buffers 最高 8；這次只有兩個段邊界，不能據此證明長程佇列不累積。

正式自動封存、發布、來源清理及 compiler 完成訊息已確認；來源目錄留空，四檔與 dataset 留在本機。各檔 checksum、Zarr／Parquet 配置、延遲與佇列數值見[錄製核對結果](issue-21-calibration-recording.json)。此錄製為 diagnostic，不供訓練，也不計入三次完整基準流程或 30 分鐘長錄製門檻。長程驗收尚待執行。

## 首輪五次流程：未通過，來源已救回

錄製 ID `6d35daa3-fa0a-44cb-8a14-a2cc29570b86`，五個回合擷取跨度合計 1,838.5788647 秒（30 分 38.6 秒），保存 35,771 幀。scheduler 遺失 11 slots，`no_free_buffer` 994，GPU readback error 與 writer backpressure 均為 0；遺失 1,005／預期 36,776 slots，約 2.73%，超過 1% gate。busy buffers 取樣最高 12、writer queue 最高 10。成功流程數與時長達標不能抵銷掉幀失敗。

原發布在 compiler 最後的 loader 核對報 `Invalid lifecycle marked trainable`。跨回合 F9 落在上一回合 final 後的區間，compiler 把此 unknown control 回寫到已完成回合，卻仍保留 final transition 的 valid，造成自相矛盾。compiler 與 loader 現在只讓同回合 unsupported input 改變該回合 lifecycle；跨界區間仍無效，原始 F9 及 bootstrap=0 均保留。回歸測試先重現同一例外，再以修正通過。

使用原四檔 evidence 重新編譯至 `runs/live/issue21-five-flows-fixed`，35,770 筆 transition 已通過 loader 並發布 COMPLETED。原始五回合均記 success；編譯後四回合有效，第三回合有真正的同回合 Alpha3 輸入，仍標為 unknown_control，沒有放寬訓練有效性。原失敗的 `.source.dataset` 未覆寫、未補上 COMPLETED；原四檔與既有 27 份 evidence manifest 雜湊核對未變。

## checkpoint 修復與重測版本

段邊界等待隨 sidecar 增長，末段約 1.1–1.2 秒，超過 12 個 buffers 在 20 Hz 的 0.6 秒容量。同步 checkpoint 每段重新雜湊累積 sidecar 是已定位的阻塞來源。修正為先 flush 並凍結 prefix 長度，再由單一背景工作計算固定 prefix 雜湊；下次 checkpoint、Seal、Finish 等待並傳遞錯誤，不允許無界累積工作。封存格式及完整性核對不變。

程序終止回歸測試在 checkpoint 後追加 frame／event，確認恢復只取核准 prefix；另注入 checkpoint 寫入失敗，確認 Finish 傳遞 IOException、不發布來源。桌面 .NET 4.7.2 探針使用實際 67 MB events，比較 Checkpoint 呼叫返回時間：修正前 103.4929 ms、修正後 31.9775 ms，後者 Finish 等待 52.0516 ms。這不是 Unity 長錄製量測，仍需以新實機掉幀結果判定修復成效。

修正 commit `fb33a33`。Release 建置 0 warnings／0 errors，mypy 17 檔通過，完整 pytest 138 項通過（166.67 秒，`tmp/issue21-five-flows-fixes-tests.xml`）。Standards 與 Spec 獨立複核未發現阻擋項；Spec 明確保留品質 gate 失敗。

使用者正常關閉遊戲後部署 DLL，SHA-256 `78750e7abb85a2f36ed36bc86df4a8671748d6e82b9dc383bf4025094d1f3b3f`；前版 DLL 與設定備份在 `runs/issue21-checkpoint-deployment`。冷啟動 F6 候選 `c5012e33b36ad6bee773f36ed39f685811008fd351ca2e7bff15459e18882cb2` 已核對 11 個磁碟檔案及 options.xml，除 recorder DLL 外與前版一致，保存於 `runs/issue21-runtime-20260913.json`。新指紋已核准，控制校正尚待完成。

## 重編譯資源與容量限制

原取樣器最後一筆在 2026-09-12，沒有涵蓋隔日五次錄製及原合併，不能補推這兩階段的 RAM／磁碟峰值。新取樣器涵蓋離線重編譯；[原始取樣](issue-21-five-flows-compile-samples.ndjson)、[編譯資源](issue-21-five-flows-compile-resources.json)及[容量計算](issue-21-five-flows-capacity.json)分開保存。

以程序開始至首次消失取樣作耗時上界，編譯至多 844.537628 秒、吞吐至少 42.3557 幀／秒；OS peak working set 1,758,404,608 bytes，5 秒取樣 private bytes 最高 2,489,139,200。此工作與回歸測試及 checkpoint 探針重疊，不能當作閒置主機 benchmark。E 槽 free 差值也包含其他工作，不能當作編譯獨占磁碟峰值。

實際 evidence 10,040,342,584 bytes、compiled dataset 17,152,919,981 bytes，按擷取跨度換算為 18.3092 與 31.2794 GiB／小時。這輪掉幀超標，且缺原合併資源量測，暫不以下修 #12 的保守容量計畫；既有資料及保留的失敗 dataset 另計。新長錄製須保持取樣器運作，重新核對低於 1% 掉幀、有效寫入率及佇列趨勢，再補齊錄製與合併資源峰值。

新版校正錄製 `6d5c13b8-9ecc-4e2c-88a3-60ad7c969581` 已通過[44 項控制核對](issue-21-checkpoint-calibration-live.json)，發布並核准 `runs/issue21-6d5c13b8-calibration.json`，SHA-256 `7f45bc3b44bff9c85bfd079e1897e2ab60d5490b1a5aae7dee45b2d50d698fff`。完整 RGBA、406 幀 RGB 比較及模型視窗讀回通過；20.3602377 秒，掉幀 0.490196%，19.8917 Hz，詳見[新版短錄製核對](issue-21-checkpoint-calibration-recording.json)。此短探針不取代新長錄製。

首輪額外核對已完成，耗時 604.283117 秒：原四檔完整驗證、35,771 幀 RGB 比較及 17,889 個模型視窗全部讀回通過，詳見[五次流程完整核對](issue-21-five-flows-live.json)。有效寫入率 19.4530682 Hz 達標，掉幀率 2.7327605% 未達標。資料完整性修復不代表錄製品質通過。舊資料核對結束後，另啟動 `runs/issue21-checkpoint-retest-resources.ndjson` 取樣新長錄製，避免離線逐幀工作干擾重測。
