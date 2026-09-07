# 無損儲存原型

回答[驗證原始錄製資料的無損儲存方案](https://github.com/JayWu07291/DSP_Dreamer/issues/11)。這是決策用拋棄式原型，正式儲存方向已由使用者確認，原型不等於正式版驗收。程式承接 `codex/prototype-issue-4-recorder`，存於 `codex/prototype-issue-11-lossless`。

## 目前結果

最新實機確認：[20260907T044718Z](evidence/live-20260907T044718Z/review.md) 已由遊戲自動完成合併、驗證與清理，無人工重試；1,199 幀獨立重解碼通過，目錄只剩四檔。

20260907T043258Z 實機已觸發自動 worker，但暴露 GUI 父程序提供無效 console handle 的問題。已修正部署的 Python 子程序啟動方式，三個 handles 皆無效的回歸測試通過，並完成本次錄製的重試與清理。見[實機修復紀錄](evidence/live-20260907T043258Z/review.md)。DLL 維持 0.1.17。

0.1.17 已加入錄製後自動合併與清理。`prepare` 會部署 Python worker 並開啟 `AutoFinalize`，FFV1 停止且 writer 排空後自動啟動背景程序。先重驗來源，再合併與完整核對，最後發布 manifest，才刪除該次 run 中清單列出且 hash 一致的暫存段、索引及報告。成功後 run 根目錄只剩 `recording.mkv`、`events.ndjson`、`frames.ndjson`、`manifest.json`。合併期間不能開始下一次擷取，遊戲仍可操作；背景解码會使用 CPU 與磁碟。

失敗時查看該 run 的 `.finalizing/error.txt`，來源或已驗證的最終資料會保留。可用 `probe.ps1 finalize -RunDirectory <該次run>` 重試，發布及清理中斷均可續做。此命令會在成功驗證後清理所指定 run 的暫存來源，請勿拿舊實驗原件作額外測試。重複對已完成 run 執行不會改動四個最終檔。未正常寫完 summary 或仍有來源 `.partial` 的錄製交給復原流程，不自動清理。

見[自動流程驗證](evidence/auto-finalize-20260907/review.md)。副本整合測試與部署 worker 測試通過；遊戲內停止時的觸發仍待一次新錄製確認。既有原始實驗錄製未清理。

2026-09-07 已驗證錄製後合併為單一 MKV 與三個文件，見[合併驗證](evidence/merge-20260907/review.md)。執行 `python prototypes/issue-11-lossless/merge_prototype.py --run <已驗證的錄製目錄> --out <新的測試目錄>`，最終四檔在輸出下的 `artifact/`。工具只讀來源，不清理來源分段；`--stop-before-publish` 可測試未發布完成標記的狀態。`merge_checks.py --merged <成功測試目錄> --interrupted <中斷測試目錄> --out <新故障測試目錄>` 建立故障副本並驗證拒絕行為。

見 [RESULTS.md](RESULTS.md) 與 `evidence/`。FFV1 與每幀 gzip 分塊均通過離線逐幀 RGBA 核對；FFV1 長程、raw 對照、RAM 與初始化修正確認已完成。[儲存決議](PROPOSAL.md)已由使用者確認。正式錄製器仍需重新驗收。

## 一個命令準備實機測試

先關閉 DSP，在 repository root 執行：

```powershell
.\prototypes\issue-11-lossless\probe.ps1 prepare -Codec ffv1
```

此命令建置 probe 0.1.17，將原 DLL、設定及既有 finalizer 備份到 `out/deployment-backup-<UTC>/`，設定 20 Hz、1800 秒、每段最多 200 幀，部署到既有 probe 位置。新資料寫入 `BepInEx/plugins/DSPDreamerCaptureProbe/runs-lossless/`，既有 `runs/` 不變。預設使用本機已安裝的 FFmpeg 6.1.1；可用 `-Ffmpeg` 指定另一個 executable，但版本變更需要重測。

1. 開啟 DSP，使用 1280×720、60 FPS，載入可操作的場景。
2. 按 `Ctrl+F8` 開始。錄製會在 30 分鐘後自動停止，期間 probe 狀態面板隱藏。
3. 過程涵蓋科技樹、背包、合成器與機器面板，文字／游標互動、移動／快速轉動視角、建造與拆除。可自由安排，不要求重新完成全部十六項微任務。記下做過的內容與任何卡頓。
4. 若需中止，按 `Ctrl+Shift+F11`，或 `Ctrl+F8` 正常停止。短錄製保留，但不能通過 30 分鐘門檻。
5. FFV1 停止後會自動合併、驗證並清理，等待畫面顯示完成。只有停用 AutoFinalize 或其他 codec 的舊分段流程才手動驗證：

```powershell
.\prototypes\issue-11-lossless\probe.ps1 verify
```

`verify` 會完整解碼每段，對照 capture index 與原始事件，才新增 `.sealed.json`。回報 numeric gates、未完成段與驗證細節。畫面內容與操作覆蓋仍需人工確認。

之後關閉 DSP，使用 `prepare -Codec raw` 安排相同設定與相近操作的原始 RGBA 對照。若仍需要驗證 gzip 的實機取捨，使用 `prepare -Codec gzip1`。每次皆建立新 run。raw 30 分鐘約 30.9 GiB，僅含影像；FFV1 的容量須以新 run 實際值為準。

2026-09-06 已完成第一次 FFV1 30 分鐘測試、raw 10 分鐘對照及 FFV1 5 分鐘 RAM 補測。RAM 已取得有效值，但補測第一幀停頓造成 capture slots 短暫耗盡。0.1.16 把第一段初始化移到 capture 計時前，離線跨段測試通過。下一步採 `prepare -Codec ffv1 -Seconds 60`，重新啟動 DSP 後做第一次錄製，核對首次啟動是否仍有槽位壓力。這份短測不替代先前長程證據。

## 可重跑的離線比較

```powershell
.\prototypes\issue-11-lossless\probe.ps1 benchmark
```

使用既有三份錄製，保存整份來源的 checksum、summary、來源原型 commit、片段 ordinal、逐幀 capture 欄位、RGBA hash、編碼參數、工具版本、CPU core-seconds、10 ms 取樣 RSS、大小、吞吐與 16 幀讀取成本。`out/` 包含大型測試副本且不進 Git。`evidence/` 只保存小型量測與索引。

獨立 C# writer 測試程式是 `StorageSmoke.csproj`。它引用錄製器使用的同一份 `PrototypeFrameStorage.cs`，以真實 RGBA 執行 200／200／5 幀分段。最後加上 `crash` 會強制結束測試程式，請只用全新的 `out/` 子目錄。此測試不啟動或終止 DSP，也不代表遊戲效能測試。

## 原型契約候選

- FFV1 使用 Matroska，`level=3 coder=1 context=0 g=1 slicecrc=1 slices=4 threads=4 pix_fmt=bgra`。輸入／核對格式為 RGBA，通道重排完整核對，不使用 YUV 轉換。容器的固定 20 fps 僅供定位解碼序列，不能取代 requested ticks。
- gzip 使用 `DWG1` magic，後接重複的 little-endian uint32 長度與一幀的 gzip member。C# 使用 `CompressionLevel.Fastest`，Python 比較使用 gzip level 1。索引額外保存 `encoded_record_offset`，目前 Python 片段讀取跳過 prefix records，尚未實作直接 offset seek。
- `capture_id`、request-time `requested_ticks`、`game_tick`、`unity_frame` 與游標欄位保留。新 session 記錄 `stopwatch_frequency`，capture ID 是擷取要求序號。原始事件仍 append-only，scheduler gap 與失敗 capture 明記。
- `segment` 加 `decoded_frame_index` 定位壓縮畫面。200 幀是候選上限，在穩定 20 Hz 下約 10 秒；有 gap 時不能稱為精確 10 秒。未滿段在正常停止時關閉。
- `.partial` 是未完成段；關閉檔案並 flush 後產生 `.unverified.json`。成功關閉或 `capture_written` 都不等於已驗證。完整解碼核對後另寫 `.sealed.json`，包含 encoded checksum、index checksum、逐幀 RGBA hashes、尺寸、格式與版本。
- capture slots／writer queue 共用 12 個 RGBA buffers，640×360 共 10.55 MiB。writer 同步串流到 gzip 或 FFmpeg stdin，不建立 raw staging，也沒有無界的待編碼幀清單。gzip 當前壓縮緩衝、FFmpeg 與遊戲程序另占記憶體。
- FFmpeg 無進展超過 5 秒時終止該 encoder，writer 記錄失敗並停止錄製。故障 run 不能通過驗收。每秒 `storage_sample` 保存 queue、遊戲 CPU/RSS、encoder 累計 CPU 與已取樣峰值；每個 capture 記錄 writer queue depth 與寫入延遲。
- 封存前解碼在停止後執行，不在錄製時競爭 CPU。錄製後未完成解碼驗證的完整 segments 全部標示 unverified，不能送入正式資料编譯。正式錄製器是否需要背景持續驗證，留待本票決議。

## 故障恢復

原始與測試 evidence 都不刪除。已驗證段的 encoded／index checksum 若改變，驗證器拒絕通過。當前未完成段只回報依 index hashes 可核對的連續 prefix，不自動升格為 sealed。

```powershell
& 'C:\Users\jay07\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  .\prototypes\issue-11-lossless\storage_probe.py recover `
  --file '<測試副本.mkv.partial>' --index '<segment.index.ndjson>' `
  --codec ffv1 --out '<新的 recovery.json>'
```

突然斷電、OS／磁碟故障與電腦重啟後的 durability 尚未驗證。`Flush(true)` 和程序強制停止測試不能證明硬體斷電安全。完整已關閉 segments 的 checksum 與索引仍需重驗；沒有完整性證據的畫面不得靜默補幀或接受。

## 還原部署

關閉 DSP 後，將指定 `out/deployment-backup-<UTC>/` 中的 DLL 與 `.cfg` 複製回原路徑即可。備份內 `deployment.json` 記錄此次部署資訊。不要使用另一張票的備份覆寫目前模組。
