# Issue #21 正式實機驗收

更新至 2026-09-14。新版六次流程已通過長錄製品質核對，單次失焦／回焦八項檢查與離線長合併資源補驗完成。最新完整回歸為 139 項通過、1 項遭 Smart App Control 阻擋，未宣稱全套通過或關閉 issue。以下按實作與驗證時序保留先前失敗；#16、#17、#18、#20 的既有結果只作為前置證據。

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

## 2026-09-14 六次自然流程與 finalize 效能

新版錄製 `9a3dccda-e332-4a6d-80f3-d99c16485c12` 保存 40,679 幀，六回合擷取跨度合計 2,034.6273185 秒，即 33 分 54.6 秒。scheduler 遺失 17 slots、no_free_buffer 2，GPU readback error／writer backpressure 均為 0。遺失 19／預期 40,698，掉幀率 0.0466853%，低於 1%。原始六回合均 success；編譯後第三與第六回合因 V／CapsLock 的同回合 unknown_control 標為無效，其餘四回合有效成功。沒有為達標忽略不支援輸入。

使用者回報 F8 結束至 COMPLETED 與 Ready 約 30 分鐘。[資源原始取樣](issue-21-six-flows-resources.ndjson)及[分階段報告](issue-21-six-flows-resources.json)保留本輪錄製至 finalize worker 結束。UTC 15:32:21 worker 啟動、15:39:38 首次見 evidence manifest、15:44:44 首次見 dataset 目錄、15:57:28 首次見 COMPLETED、16:00:18 最後見 worker，時間解析度約 5 秒。從 worker 啟動至 COMPLETED 約 25 分鐘，加最後讀回約 3 分鐘，符合使用者觀察。

source 目錄最後清理時點約 15:43:01，推定 publication／核對／清理共約 10 分 40 秒；compiler 至 COMPLETED 約 14 分 24 秒。這不是只量 mux 的時間，也不能用 dataset 目錄首次出現代替 compiler 開始，因為 compiler 先驗證 evidence。RGB 第一個 chunk 至最後一個 chunk 的修改時間相差 528.98879 秒，是這次定位到的主要 compiler 成本。

取樣器有錄製與封存期的 DSP／FFmpeg 資源，但只捕捉到遊戲啟動的 Python launcher，沒有實際 interpreter。不可把 launcher 的約 26 MB working set 宣稱為 compiler RAM 峰值。磁碟 free 差值包含其他程序。另以代理直接啟動完整重編譯補量 compiler 資源；原 finalize 的 interpreter RAM 仍屬缺漏。

實際 128 幀畫面對照探針：單幀寫入 1.173103 秒、32 幀批次 0.351489 秒；讀回分別 0.311321／0.150107 秒。這是短探針，且與離線核對重疊，不直接外推整段改善比例。回歸測試先重現 205 次同步寫入，再限制批次總數與最多 32 幀暫存，核對所有像素、原單幀 chunk、最後不足批次的 checksum 拒絕。32 幀 RGB 約 21 MiB；事件／轉移 metadata 與 Zarr codec 額外記憶體另計。既有發布、清理、完整來源解碼及發布後讀回全部保留。

Standards：未發現硬性違反。固定批次大小不新增設定或依賴。Spec：未發現缺漏、scope creep 或錯誤；不以 raw 品質達標代替完整驗收。完整長錄製核對與批次重編譯實測結果見下文。

使用者確認六次包含主要 UI／游標、快速移動、建造與拆除，已播放影片；尚未做失焦與按鍵釋放測試。使用者觀察 F9 前短段不在影片中。核對[回合終點](issue-21-six-flows-endpoints.json)及 `EpisodeLifecycle.EpisodeUpdate`／`CaptureLoop`：成功時自動 EndEpisode，補最後一幀後不再擷取，直到 F9 開始新回合。前五次 success 至 F9 分別 5.2363、5.6213、5.1363、4.4518、7.5193 秒；最後 capture 均在 success 後 16–28 ms 且 final node=1。這是成功後未擷取的等待時間，不是封存漏幀；連續影片不是完整桌面實況錄影。播放確認仍保留使用者此觀察，沒有更改回合邊界。

六次長錄製完整核對已完成，詳見[完整報告](issue-21-six-flows-live.json)：40,679 幀 RGBA／RGB 與 20,343 個模型視窗全部通過，有效寫入率 19.9903931 Hz。writer queue 首末十分位平均 0.20998／0.26875，busy buffers 1.33882／1.40595，未見平均佇列隨時間持續累積；成功 capture 取樣仍不能排除瞬時峰值。最高 busy=12、writer queue=10，兩個 slot 不足已如實計入掉幀。

實際 evidence 為 11,506,866,919 bytes，dataset 19,669,956,713 bytes，按擷取跨度分別為 18.9615943 與 32.4131444 GiB／capture 小時。合計約 51.3747387 GiB／小時，十小時約 513.7474 GiB，再加至少 1 GiB scratch 與所有既有資料；若保留舊 compiled dataset，須額外加上該份完整容量。這是此場景壓縮結果，不保證其他畫面有相同比例；仍保留未壓縮 RGB 的 compiler 容量預檢。合併另需 source／工作複本預留，不能把最終四檔大小當作合併峰值。

效能診斷使用 cProfile 的完整 verifier 耗時 776.027917 秒，包含正式 loader、額外逐幀比較及逐模型視窗讀回，且與回歸測試部分重疊，不是正常 finalize benchmark。其顯示約 122,000 次同步 Zarr 讀取，支持逐幀 I/O 開銷的診斷。正式批次修改的全套 pytest 139 項通過，173.75 秒，JUnit `tmp/issue21-batched-io-tests.xml`；mypy 17 檔通過。修改已提交 `900781f`，只改 Python 與文件，不需更換 DLL 或重新校正。

本版短失焦診斷未全數通過，保留失敗結果：[第一次](issue-21-focus-hold-live.json) `9a9b714d-837c-4375-a6ac-8fed5ee07a21`，140.1743 ms 首次觀察空 held，766.6 ms 回焦且空 held，但 2,214.38 ms 有新 Mouse0 輸入，使 observed_release 的持續空白檢查失敗；[第二次](issue-21-focus-hold-retest-live.json) `97661b8b-d56c-49c0-8ead-b0ef98d4be86`，103.1409 ms 首次空 held，後續保持空白，但 176 筆、至 2,989.87 ms 的觀察全為 focused=false，refocused_empty 失敗。兩次均確認模型 W 原先按住、release_all 成功且沒有後續模型要求；不合併兩份局部結果宣稱完整診斷 gate 通過。設定已恢復 Diagnostics=false、Case=full，保留目前已核准校正。

本輪完整重編譯有上述兩次短診斷／其自動編譯的少量重疊，會保留在資源取樣，不宣稱閒置主機的排他 benchmark。這不降低資料一致性比較要求。

批次完整重編譯已完成，輸出 `runs/live/issue21-six-flows-batched`，[計時與一致性結果](issue-21-six-flows-batched-compile.json)記錄 compiler PID 38976。編譯含來源完整驗證及發布前 loader 共 527.8062865 秒，即 8 分 48 秒，對照原約 14 分 24 秒縮短約 39%；額外正式讀回 129.8476573 秒，即 2 分 10 秒。兩段合計 657.6539438 秒，即 10 分 58 秒。RGB chunk 首末寫入跨度由 528.9887898 秒降至 225.4186506 秒，約縮短 57%。原階段起點只有取樣及檔案時點可定位，對照時間與百分比均為近似，不是同時執行的嚴格 A/B 基準。

所有新舊影像 chunk 與 Parquet 檔案 checksum 完全一致；dataset metadata 除新 artifact_id 外完全一致。新版 COMPLETED SHA-256 `9fd31a2836e2d71f6d1a6de63ebb637a39c32b4e6dc103196b23103bd6c45344`。原六流程 evidence／dataset、首輪失敗 dataset 及其他舊資料全部保留，原有 27 份 evidence manifest 再次核對未變。報告的 `complete_successes` 明確指 raw source 成功回合數 6，不是 compiled 有效成功回合數 4。

此次未重跑整個 F8 至 Ready 的合併／清理流程，不把 10 分 58 秒稱為總 finalize 時間，也不宣稱已量到新總等待時間。#21 仍未全數通過：本版單次失焦／回焦診斷未全數通過，原長合併的 Python interpreter RAM 峰值缺漏。未關閉 issue，未以短診斷或 launcher 記憶體填補長錄製資源證據。

[批次編譯資源](issue-21-six-flows-batched-resources.json)與[原始取樣](issue-21-six-flows-batched-resources.ndjson)已保存。compiler 105 筆取樣，OS 回報 peak working set 2,014,167,040 bytes，約 1.88 GiB；取樣 private bytes 最高 2,774,491,136 bytes，約 2.58 GiB。readback 的 OS peak 沿用同一程序先前峰值，不把它解讀為該階段新增需求。磁碟 free 最低值分段列於 JSON，包含短診斷與其他工作，不能宣稱獨占磁碟峰值。取樣器已停止。

重編譯後 `runs/live` 全部保留資料的 logical bytes 為 169,612,412,780，包含新版重編譯副本、兩輪長錄製、失敗資料與診斷；E 槽 free 1,188,024,897,536 bytes。容量預算應加上這份目前保留量，不再只用最早的 73,893,112,235 bytes。Git 對驗收 NDJSON 固定 LF，以便報告中的原始取樣 SHA-256 在不同平台 checkout 後仍可核對。

## 失焦與長合併資源補驗

第三次短測試 `3b01b5c3-cfb2-474a-ad2f-dfa32d7bcd45` 已在同一次錄製通過全部 8 項檢查，見[失焦最終結果](issue-21-focus-hold-final-live.json)。模型 W 確實按住後失焦，release_all 全數送出成功；62.4312 ms 首次觀察空 held，之後保持空白，回焦也空白，沒有後續模型要求，正式 dataset 發布成功。未修改三秒觀察窗或放寬 verifier；前兩次失敗結果仍保留。已恢復 Diagnostics=false、Case=full。

原長錄製的來源分段已在成功發布時正常清理，因此長合併資源以原四檔影片的 stream copy 重建 204 個分段，保留 40,679 幀的原始 frames／events 位元組及錄製工作階段身分。封裝 bytes 可能與原分段不同，不聲稱恢復原容器 checksum；正式 publisher 仍逐段、合併後逐幀 RGBA 核對並檢查所有段邊界 seek。重建 SOURCE 標有 benchmark_replay 與原 manifest 身分，這是離線重播，不是新增實機示範或新增品質樣本。

重播目錄為 `runs/issue21-merge-replay`。此根目錄限定本次來源、工作複本、輸出與量測檔，每五秒計算 logical file bytes，分別保存程序 working set／private bytes 與整個受測目錄容量，不以磁碟 free 差值冒充獨占磁碟峰值。Python worker PID 41772 已確認為實際 interpreter，launcher 為 40188；資源報告以 worker 及其直接 FFmpeg 子程序區分，PID 需配合開始時間判讀。重建分段的準備階段不計入正式 publication／cleanup 耗時。

可重現步驟保存為[準備腳本](issue-21-merge-replay-prepare.py)與[合併量測腳本](issue-21-merge-replay-publish.py)，均從 repo 根目錄執行；固定 artifact 名稱存在時拒絕覆寫。合併採正式 `publish(..., cleanup=True)`，不變更 production 程式，完成後核對原始 sidecar 身分、回合與幀數、來源清理及原 manifest 未變。

離線重播未重建原先已清理的 203 個 checkpoint／encoder 附屬檔；原 manifest 記載這些檔案合計 3,186,963 bytes。重播的分段容器與新 SOURCE 封裝也可能有 byte 差異，因此量測代表同一組長畫面與事件的正式合併工作負載，不回填為歷史實機 finalize 的精確峰值。容量預算須另保留這些附屬檔及既有 scratch 餘裕。

[合併結果](issue-21-merge-replay.json)記錄 UTC 16:39:03.877160 至 16:50:54.525329，正式 publication、完整核對與來源清理共 710.64835 秒，即 11 分 50.6 秒。40,679 幀完整 RGBA 解碼及 408 個 seek 位置全部通過，sidecar 位元組一致，原 manifest 未变，來源清理成功。此時間不包含重建準備或 compiler，也不是重新量測整段 F8 至 Ready。

[資源報告](issue-21-merge-replay-resources.json)附[程序原始取樣](issue-21-merge-replay-processes.ndjson)與[目錄容量原始取樣](issue-21-merge-replay-storage.ndjson)的 SHA-256、worker 開始時間及量測區間。程序取樣使用 `tools/measure-recorder.ps1 -Out runs/issue21-merge-replay-processes.ndjson`。實際 worker 共 141 筆，OS peak working set 1,245,028,352 bytes（1.16 GiB），取樣 private bytes 最高 1,824,026,624（1.70 GiB）；worker 加直接 FFmpeg 子程序的同時取樣峰值分別為 1,263,968,256 與 1,904,115,712 bytes。OS 累積峰值與定時取樣峰值分開呈現，不混算。

受測目錄 logical bytes 最高 34,415,832,800（32.05 GiB）。142 筆容量取樣從 UTC 16:39:03.879675 至 16:50:51.191318，最大間隔 5.2816 秒；起點差小於一秒、尾端差小於六秒，未見取樣中斷，但仍可能漏掉兩筆間瞬時峰值。重播保留資料 11,506,855,483 bytes 位於 `runs/live` 之外，容量帳須在前述既有資料量之外另加；不刪除旧資料以降低峰值。

量測完成後，保存的合併腳本補上「主執行緒先拒絕既有取樣檔」及「背景取樣失敗必須使報告失敗」，另核對 replay marker 與 session 身分；這些防護不是原量測當時的腳本版本。[取樣失敗檢查](issue-21-merge-replay-sampler-check.py)已通過，原始量測另外核對上述覆蓋區間與 hash。compiler 與正式實機驗收入口均拒絕 `benchmark_replay`，避免離線副本被計為新的訓練資料或實機樣本。新增拒絕測試先重現失敗、修正後通過；mypy 17 檔通過。

## Smart App Control 阻擋補充回歸

兩項實測完成後的完整 pytest 為 139 passed、1 failed，耗時 157.16 秒，JUnit 保存於 `tmp/issue21-final-verification-tests.xml`。失敗項 `test_native_action_contract_matches_model_codec` 的 .NET 建置成功，但啟動 `tests/ControlReplay/bin/Debug/net472/ControlReplay.exe` 時收到 WinError 4551。該檔 Authenticode 狀態為 NotSigned；[Code Integrity 紀錄](issue-21-smart-app-control.json)於台灣時間 2026-09-14 00:53:33 記載 3033／3077／3118，指出簽署等級未符合政策而被封鎖。這是環境封鎖，該測試尚未在本輪完成，不以其他測試代替。

保留 Smart App Control，未修改政策、繞過封鎖或重試被擋的程式。此封鎖发生在失焦與長合併完成之後，未使已保存的兩項結果失效。Standards／Spec 複核要求的 replay 身分限制、取樣失敗傳遞及 RAM 原始證據連結均已補齊。
