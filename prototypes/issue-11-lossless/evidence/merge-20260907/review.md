# 單一 MKV 與整併文件驗證

使用者要求錄製後留下單一可播放 MKV，文件各自整併，不使用封裝檔，也不保留大量 segment。以既有錄製唯讀驗證，另存測試輸出。

| 來源 | 分段／幀數 | 結果 |
| --- | --- | --- |
| 20260906T162147Z | 6 段、1,198 幀，尾段 198 幀 | 全幀 RGBA hash、20 fps PTS、12 個 seek 位置全部通過；6,131 筆事件 byte-identical |
| 20260906T135528Z | 180 段、35,989 幀，尾段 189 幀 | 全幀 RGBA hash、20 fps PTS、14 個 seek 位置全部通過；193,571 筆事件 byte-identical |

長錄製原始影像 9,258,245,010 bytes，單一 MKV 9,258,206,066 bytes，已涵蓋超過 4 GiB。單純 remux 13.98 秒，來源 checksum、remux、逐幀解碼 hash、seek 與輸出 checksum 合計 96.98 秒。短錄製分別 0.41 秒與 4.10 秒。單次本機量測，受磁碟快取影響，未量測額外 RAM 與磁碟峰值。

每份 `artifact/` 恰有四檔：`recording.mkv`、`events.ndjson`、`frames.ndjson`、`manifest.json`。逐段索引合成單檔，新增全片 `video_frame_index`，逐筆回讀比對；原本 capture 身分、request ticks、段內 ordinal 及 hash 保留。來源原型的 `storage_state` 與 summary verification 欄位保留作歷史資料，最終狀態讀新 manifest。原始 events 已是 session 單檔，所以以 byte-identical 複製驗證，未測多個事件分片的整併。原型缺少全域 sequence_number，正式版仍須補足。

使用 FFmpeg 6.1.1 concat demuxer 加 stream copy，明確指定每段 duration 為實際幀數／20，以免容器 duration 捨入累積。整支影片最後 PTS 分別 59.85 秒與 1799.40 秒。播放時間壓縮了 scheduler gaps，原始時間與 gap 仍在文件中。完整解碼並核對每個 PTS；短片檢查每個接合處兩側，長片抽查前、中、後接合處及尾幀。另檢視短片六張預覽，面板、遊戲畫面與接合處顯示正常。

故障副本測試通過：

- 發布 manifest 前受控停止，讀取端拒絕，來源仍存在。
- 影片截斷至一半 bytes，在第 709 幀停止，完整驗證拒絕。
- 已發布形狀的副本中改動事件一個 byte，checksum 核對拒絕。

這些證據確認合併及 FFmpeg 解碼／seek，可供支援 FFV1 的播放器讀取；尚未操作互動式播放器。受控停止不是任意時間程序終止或斷電測試。自動清理來源、清理中斷恢復、正式 compiler 及 bounded-memory 整併尚未實作。原型會把索引與事件載入記憶體，正式版須改為串流。所有原始錄製保留，測試故障副本及診斷檔位於 `out/`，不是最終四檔的內容。

詳細數值見 [short.json](short.json)、[long.json](long.json)、[failures.json](failures.json)。目前足以確認單一 MKV 與少量整併文件的方向可行，不等於正式錄製器完成驗收。
