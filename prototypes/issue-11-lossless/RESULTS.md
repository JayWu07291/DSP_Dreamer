# 無損儲存離線量測，2026-09-06

2026-09-07 更新：[單一 MKV 與整併文件驗證](evidence/merge-20260907/review.md)通過。30 分鐘的 180 段合為一支 8.62 GiB MKV，35,989 幀逐幀一致，最終四檔。來源清理與正式整合仍待實作。

使用者已確認採用 FFV1，見[儲存決議](PROPOSAL.md)。[首次實機驗證](evidence/live-20260906T135528Z/review.md) 通過 20 Hz、30 分鐘完整性與擷取數值門檻，影像比同幀數 raw 少 72.1%。[Raw 對照](evidence/live-20260906T151649Z/review.md) 也通過。[RAM 補測](evidence/live-20260906T153540Z/review.md) 得到 encoder 74.1 MiB、DSP 約 4.20 GiB，並暴露首次啟動停頓；[修正後的遊戲確認](evidence/live-20260906T162147Z/review.md) 第一幀 9.89 ms，無槽位耗盡。儲存表示已確認採用單一 MKV 與三份文件，資料契約修訂由決策票回寫。下方保留先前離線量測與當時的待辦。

## 相同來源的比較

每個候選使用相同 1,233 幀，共五個片段。來自含合成游標的 20 Hz、30 Hz 短錄製與 1 Hz 十六項微任務錄製。五段都逐幀解碼核對 RGBA SHA-256、幀數與順序；另有含不同 alpha 值的合成資料通過往返。UI、文字、游標與建造內容已由來源預覽確認；快速移動的完整覆蓋仍留給實機操作。

| 來源及 written-frame ordinal | 幀數 | FFV1 GiB／20 Hz capture 小時 | gzip GiB／20 Hz capture 小時 | FFV1 encode fps | gzip encode fps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20260901T024749Z，0 起 | 200 | 7.54 | 16.65 | 276.2 | 91.5 |
| 20260901T024749Z，400 起 | 200 | 15.00 | 31.66 | 192.7 | 58.0 |
| 20260901T024749Z，1000 起 | 200 | 16.28 | 33.50 | 188.0 | 55.6 |
| 20260901T025133Z，1200 起 | 200 | 19.01 | 41.27 | 175.0 | 44.9 |
| 20260902T145501Z，0 起，1 Hz | 433 | 20.03 | 38.25 | 169.6 | 50.2 |

容量以 encoded bytes／幀數 × 72,000 計算，只包含影像。最後一列的素材以 1 Hz 擷取，換算容量不能當成已錄到 20 Hz 的證據，也不能以這些片段推定完整訓練資料的壓縮倍率。capture 小時不是人工工時。

FFV1 解碼加 hash 為 124–212 fps，gzip 為 175–266 fps。FFV1 編碼平均使用 2.92–3.88 個 CPU core，gzip 約 0.96–0.99 個。程序 RSS 的 10 ms 取樣峰值為 FFV1 103.5–166.8 MiB、gzip 46.7–112.2 MiB；這是 Python 與當次 codec 程序總和，包含載入的 metadata，不能直接当成純 encoder RAM。測試依序執行，檔案快取可能已暖，沒有重複次數或信賴區間。

從片段中點取 16 幀，FFV1 花 637–1,827 ms，gzip 62–128 ms。現有 FFV1 reader 從段首解碼到 ordinal，再取片段，沒有最佳化 seek。gzip reader 掃描並跳過前方壓縮 records。不同讀取實作造成的差距需要一併評估，不能全歸因於 codec。

完整資料併存容量仍需量測：既有 evidence + 新壓縮 evidence + events／index + compiled dataset + compiler 暫存。本原型串流寫入，不產生 raw staging；12 個 capture buffers 共 10.55 MiB，encoder 與 gzip 當前壓縮緩衝另計。此次 benchmark 測試副本與原始錄製同時留在本機，未刪除任何既有錄製。

## 實際 C# 寫入路徑

錄製器與 `StorageSmoke.csproj` 共用 `PrototypeFrameStorage.cs`。兩候選都完成 405 幀、200／200／5 三段，解碼 hash 對照錄製時 index 後，再獨立對照原始 `frames.rgba`。正常結束、完整段邊界與不足一段的結尾均通過。原始 raw writer 仍可作實機對照。

FFV1 資源量測曾在 encoder 結束後呼叫 .NET `Process.PeakWorkingSet64` 而失敗。現在存活時取樣記憶體，CPU 透過保留的 process handle 讀取，原始 405 幀測試重新通過。此修正與證據都只屬於原型。

writer 使用同步串流與 12 個共享 capture slots。分段切換的最長延遲目前僅為離線量測，無法保證與 GPU readback、遊戲主執行緒並行時不掉幀。必須觀察實機 queue／gap／drop／write rate。

## 故障副本

五段、兩候選各截斷至 encoded 檔案的 75%，全部被 checksum／完整幀數驗證拒絕。只接受 hash 一致的連續 prefix。不同片段恢復幀數見 `evidence/*-result.json`；不能用相同 byte 比例推定 frame 比例。

另外在第二段第 5 幀後強制終止 C# 測試程式。兩候選的第一段 200 幀均可完整驗證，第二段維持 `.partial`。這次 FFV1 可恢復 5 幀，gzip 因未 flush 的小段恢復 0 幀。FFV1 子程序仍能收到 pipe EOF 後處理緩衝，這不是同時殺死所有程序或突然斷電測試。可恢復範圍必须以保存的 index 與 decoded hash 實際核對。

任何 `.partial` 或缺少完整驗證的 segment 都不能冒充 sealed。此實作不自動修復、重寫或刪除 evidence。

## 實機測試待辦

已提供 `prepare` 與 `verify` 命令，預設 FFV1、20 Hz、1800 秒，每段最多 200 幀。使用者操作包含 UI、文字／游標、快速移動與建造。實際有效 Hz 至少 19、總掉幀低於 1%、GPU readback error 與 writer backpressure 為零，queue 不持續累積；全部段完整解碼核對。接著以 raw 進行相近操作對照，必要時驗證 gzip。

尚待記錄完整實機 CPU／RAM／queue 峰值、影像與事件容量、操作內容、畫面目視核對、與 raw 的差異。compiled dataset 與 compiler 暫存峰值、正式錄製器工時修訂，以及使用者對容量／讀取成本的取捨，也尚未決定。本票維持開啟。

## 重現與來源

`evidence/environment.json` 保存 FFmpeg 6.1.1 build 字串、executable SHA-256、Python 3.12.14、zlib 1.3.2 與來源原型 branch commit。來源 commit 是讀取格式的程式參考，舊 run 並未全部嵌入 recorder binary 版本，不聲稱它是每個 run 的精確 build。每份原始 RGBA、events、summary 皆另存全檔 checksum，逐幀來源以 run ID、event line 與 file offset 識別。

`evidence/results.json` 與個別 result 保存完整命令、大小、CPU、RSS、吞吐、讀取及截斷結果；`*-index.json` 保存 capture ID、時間、游標與逐幀 hashes。兩個 `crash-*` 資料夾保存故障驗證報告；`csharp-*` 保存同一 C# writer 的驗證結果。

FFV1 與像素格式設計參考 [FFV1 規格](https://github.com/FFmpeg/FFV1/blob/master/ffv1.md)，命令與 frame sync 語意參考 [FFmpeg 文件](https://www.ffmpeg.org/ffmpeg.html)。候選是否無損以本次 RGBA 往返證據判定。
