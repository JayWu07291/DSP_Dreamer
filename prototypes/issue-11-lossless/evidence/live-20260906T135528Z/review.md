# 首次 FFV1 30 分鐘實機驗證

錄製版本 0.1.14，run `20260906T135528Z`。180 段、35,989 幀完整解碼與 RGBA hash、capture index、時間順序一致，無 partial。各段 encoded／index checksum 見 `sealed-index.json`，完整驗證見同目錄 verification JSON。

| 指標 | 實測 |
| --- | ---: |
| 時間 | 1,800.086 秒 |
| 有效頻率 | 19.9929 Hz |
| 掉幀 | 11／36,000，0.03056% |
| GPU readback error／writer drop | 0／0 |
| writer queue 最高 | 2 幀 |
| writer 延遲 median／p95／p99 | 10.35／12.19／30.14 ms |
| 最大單次寫入／分段結束 | 92.06／81.80 ms |
| 影像容量 | 8.6224 GiB |
| 同幀數 raw RGBA | 30.8896 GiB |
| 影像節省 | 72.09% |
| 影像＋events＋indices | 8.7104 GiB |
| FFmpeg 平均 CPU cores | 0.5455 |
| DSP 平均 CPU cores，包含遊戲與 probe | 約 2.1519 |

以上容量不包含 compiled dataset、compiler 暫存及驗證報告。影像換算每 capture 小時約 17.244 GiB，只適用於這次操作內容。

每分鐘 storage queue 取樣最大值均為 0 或 1，沒有持續累積。完整 capture 的最高 queue 為 2。11 個 gap 都是 scheduler missed，沒有 in-flight drop。最大單次 writer 延遲超過 50 ms，但有界 queue 吸收這次延遲，沒有 writer backpressure。

使用者於本次對話明確確認「都有涵蓋，沒有明顯卡頓」，對應快速移動／轉動視角、面板操作、建造與拆除。事件包含 122 次面板開啟及 122 次關閉、82 次建造、6 次拆除。索引抽查畫面包含科技樹、背包、合成器、機甲面板、建造與游標，方向與色彩正常，沒有 probe overlay。這是抽查，不聲稱人工檢視每幀。預覽索引见 `preview-index.json`，圖片保留在本機 out。

59 幀記錄游標 visible 但沒有合成像素，全部 hotspot 都在 640×360 畫面邊界外。未發現 hotspot 在画面內卻零合成的列；完整 RGBA 核對仍全部通過。

舊版 summary 的 `inconclusive_or_fail` 源於它要求至少 3 次注入，本次 injected_actions=0。該要求屬於舊閉迴路 probe；本次儲存票規定的擷取數值門檻與完整性門檻全部通過，不改寫原始 summary。

## 尚未通過的項目

RAM 在遊戲 runtime 全部回傳 0，視為缺測，不能宣稱記憶體使用為零。錄製當下已結束，不能由離線解碼 RAM 反推錄製 RAM。probe 0.1.15 改用 Windows GetProcessMemoryInfo，失敗值改為 -1；獨立 405 幀 writer 測試取得自身 RSS 35,930,112 bytes、encoder peak 60,977,152 bytes。這些僅驗證修正 API 能取得資料，不取代遊戲內量測。

本機已備份並部署 0.1.15，準備 raw 20 Hz、600 秒對照。10 分鐘 raw 與 FFV1 同長度區間比較，操作需相近；不把它稱為新的 30 分鐘持續性證據。FFV1 還需補充 RAM 量測。資料集併存峰值、正式錄製器工時及最終儲存取捨仍待決議，票保持開啟。
