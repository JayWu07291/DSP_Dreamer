# 原始錄製儲存決議草案

待使用者確認，尚未修訂資料契約或關閉決策票。

## 建議採用

原始影像採分段 Matroska／FFV1，原始事件仍使用 append-only NDJSON。每段最多 200 個實際擷取成功的畫面，在穩定 20 Hz 時約 10 秒；以 frame count 分段，不把有 gap 的段當成精確 10 秒。

固定已測的 FFmpeg 6.1.1 executable，SHA-256 `04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00`，參數為 `ffv1 level=3 coder=1 context=0 g=1 slicecrc=1 slices=4 threads=4 pix_fmt=bgra`。來源及核對格式固定為游標合成後的 640×360 RGBA bytes，包含 alpha；只做可逆 RGBA／BGRA 通道重排。不以 YUV 轉換、縮放、補幀或 PTS 取代原始證據。換版本或參數後重跑相同往返與效能檢查。

gzip 分塊保留為備選原型。離線相同片段中它解碼及目前的片段讀取较快，但影像約為 FFV1 的 1.9–2.2 倍。正式 compiler 主要依序讀取 evidence，故優先節省不可變 evidence 的容量；模型訓練讀取 compiled dataset，不直接反覆隨機 seek FFV1。這不變更 Zarr／Parquet 資料集契約。

## 證據與限制

| 測試 | 結果與用途 |
| --- | --- |
| 相同 1,233 幀、兩候選 | RGBA、alpha、幀數與順序全部通過；比較大小、CPU、RAM、讀取與截斷 |
| FFV1 30 分鐘 | 35,989 幀，19.9929 Hz，掉幀 0.03056%，queue 最高 2，沒有 readback／writer 錯誤；影像 8.62 GiB，比同幀數 raw 少 72.1% |
| raw 10 分鐘 | 11,998 幀，19.9899 Hz，掉幀 0.01667%，queue 最高 1；使用者確認操作相近、沒有感覺流暢度差異 |
| FFV1 5 分鐘 RAM | 5,987 幀全部核對；encoder 74.11 MiB、DSP 約 4.20 GiB，但發現首次 Write 1.07 秒造成槽位耗盡，不宣稱無背壓 |
| 修正後首次啟動 1 分鐘 | 1,198 幀全部核對，第一幀 9.89 ms，queue 最高 1，無槽位耗盡；初始化在 capture clock 前完成 |
| 專用故障副本 | 已關閉段可重驗；截斷與強制停止後只能接受 hash 一致的連續 prefix，不自動變成完整段 |

CPU 平均 encoder 約 0.5 個 core。RAM 為短測中各程序各自的峰值，不是 30 分鐘全程的記憶體曲線，也不能把 DSP RSS 當成 recorder 額外 RAM。單次初始化成功不保證所有冷快取條件。突發斷電、OS／磁碟故障尚未驗證。所有量測與各自限制见 RESULTS.md 及 evidence 的 review。

## 初始化、時間與索引

正式版在宣告開始錄製、啟動 capture clock 與排程第一個 request 前準備第一個 encoder。準備耗時另外記錄。後續段切換在有界 writer 路徑執行，保留 12 個 capture buffers，640×360 RGBA 共 10.55 MiB；encoder 自身記憶體另計。不得以擴成無界 queue 消除掉幀。

每個 capture 保存 session ID、capture ID、正式契約的全域 sequence_number、requested monotonic ticks、clock frequency、game tick、Unity frame、游標欄位、segment ID 與 decoded_frame_index。GPU completion 時間另存，不改写 request 身分。注意原型只提供 capture ID 與事件行序，正式版仍須补上全域 sequence_number，不能把原型格式直接當正式 schema。

所有 scheduler gap、readback failure、writer failure 與 no_free_slot 都保存明確時間及原因。no_free_slot 同時保存 queue 與 outstanding readbacks；writer_drops=0 本身不能證明沒有寫入背壓。sequence 不跨 gap／fault，延續既有資料有效性契約。

## 封存與恢復

1. 未完成檔案使用 `.partial`。正常關段時 flush encoded 檔與索引，記錄 closed-unverified 狀態。
2. 停止錄製後依序完整解碼，核對 RGBA hashes、幀數、索引與時間。全部成功才發布 verified manifest，保存 encoded／index checksum、逐幀 hashes、尺寸、pixel format、參數與工具版本。正式版 manifest 用同目錄暫存檔加原子發布，不能因 marker 部分寫入而誤認完成。
3. 只允許 verified evidence 進入 compiler。失敗或未知狀態保留，不能靜默補幀、重排或接受損壞資料。
4. 異常停止後先重驗已關閉段，再對當前段核對可恢復的連續 prefix。恢復結果是新 artifact，保存來源與失效範圍，原始檔不覆寫。

預設直接串流壓縮，不用 raw staging。沒有暫存副本回收需求，也不授權刪除已有 evidence。完整解碼驗證先在錄製停止後執行，以免與遊戲爭用 CPU；正式版可以日後增加背景驗證，但需另測資源競爭。

## 容量與編譯暫存

容量以 capture 小時計算，不把約 10 小時人工示範工時等同於 10 小時有效 capture。

已測遊戲片段的 FFV1 影像換算約 7.5–20.0 GiB／capture 小時；完整 30 分鐘 run 約 17.24 GiB／小時。以下是規劃預留，不是保證壓縮上限或已實測的 compiled dataset 大小：

- 新 FFV1 影像暫以 22 GiB／capture 小時規劃，evidence events／indices 另預留 1 GiB／小時。內容變更時依已寫入速率更新預估，超出預算要增加空間或停錄，不降低無損標準。
- compiled RGB 以未壓縮 `640×360×3 uint8×20 Hz` 計算，46.35 GiB／capture 小時。每張 observation 只存一次，next-observation 使用索引，不重複保存另一份 RGB。這是形狀推導值，沒有假設 Zarr 壓縮倍率。
- compiled tables／array metadata 暫預留 2 GiB／capture 小時，正式 compiler benchmark 量測後替換。單純讀 RGB 的吞吐不能代表完整 compiler 吞吐。
- compiler 使用單段串流解碼，不輸出完整 raw 中間影片。額外磁碟 scratch 上限建議 1 GiB，超額停止該編譯工作並保留 evidence。未完成的新 dataset 目錄算入新 dataset 本身，不重複算為 scratch。

磁碟峰值公式為 `既有 evidence + 新 evidence + 保留的旧 compiled dataset + 新 compiled dataset + scratch`。初次建立 H 小時資料，示例預算約 `71.35 × H + 1 GiB`，另加既有資料。H=10 是約 714.5 GiB；如果還保留同尺寸舊 compiled dataset 再編譯一次，約 1,198 GiB，另加既有資料。這是以以上預留量組成的排程估计，不是可放心填滿磁碟的硬上限。

正式 compiler 在首批資料前必須量測實際 files、chunk／shard、tables 與 scratch 峰值，記入 manifest，再決定後續批次可錄多久。各階段先檢查可用空間，容量不足時保留舊 evidence 並停止新增工作。不得為了通過容量門檻自動刪除舊 evidence。

## 正式錄製器工時修訂

既有學習／報告草案 D 項原估 3–5 小時，包含儲存、manifest、checksum 與恢復。建議改為 **5–8 小時**：移植分段與初始化 1–2 小時、正式索引／版本與原子封存 2–3 小時、故障／容量與 compiler 接口驗證 2–3 小時。

這是從正式實作開始的工程估計，包含 agent 工作與必要整合驗收，不是使用者手寫程式工時；已完成的原型與錄製不再重複計入。其餘項目維持原估，因此 A–F 由 21–32 改為 23–35 小時，另保留 G 的 5–8 小時緩衝，合計 **28–43 小時**。D 增加 2–3 小時是初始化、正式原子封存與容量驗證的整合預留，不承諾必定用滿，也不改動 GPU 預算與模型 gate。

## 確認後的回寫

將此票決議定為 FFV1／MKV 取代資料契約中的 raw RGBA frame chunks，旁存 append-only NDJSON、時間與有效性語意保持；回寫資料契約的修訂指標，並供學習／報告票引用容量與 D 項工時。正式錄製器仍須重新完成端到端長時間、冷啟動、重載、故障與 compiler 驗收。原型分支保留為證據，不直接合併成正式錄製器。
