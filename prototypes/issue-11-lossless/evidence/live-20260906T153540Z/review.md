# FFV1 RAM 補測與首次寫入停頓

run `20260906T153540Z`，probe 0.1.15，300.036 秒。30 段、5,987 幀全部解碼，RGBA hash、幀數、索引與時間順序一致，無 partial。完整驗證報告已保存。使用者表示沒有注意到卡頓，也沒有切換視窗。

RAM 補測取得有效值：FFmpeg peak working set 77,705,216 bytes，74.11 MiB；DSP 程序 RSS 取樣峰值 4,505,989,120 bytes，約 4.20 GiB。兩者是各自峰值，不聲稱同時出現。這是本次 5 分鐘的量測，不能追溯推定前次 30 分鐘的 RAM 峰值。FFmpeg 平均占用 0.524 個 CPU cores。

影像 1.5757 GiB，影像＋events＋indices 1.5899 GiB。相同幀數 raw 為 5.1387 GiB，本次節省 69.34%。與前次 72.1% 的差異反映不同內容，不設定固定壓縮倍率。

## 新發現的啟動風險

總有效頻率 19.9543 Hz，掉幀 13／6,000，0.2167%，GPU readback error 與 writer_drops 為零。但不能只看 writer_drops 欄位就宣稱沒有寫入阻塞。

- capture_id=1，requested_ticks=258859，首次 Write 耗時 1,072.416 ms。該方法當時包含首次 encoder process 建立、pipe 設定與第一幀寫入，舊版未分別量測各子步驟，不能指定是哪一個 OS 呼叫耗時。
- 約 1.048 秒的 storage_sample 顯示 written_frames=0、writer_queue_depth=11、outstanding_readbacks=0。12 個共享 capture slots 已由 writer／待寫入資料占用。
- 11 次 `no_free_slot` 導致 in_flight_drops；另有 2 次 scheduler gap，約 2.174 秒時記錄。
- 後續每分钟 queue 取樣最高皆為 0，第二大的單幀寫入僅 56.08 ms。這是啟動時的短暫飽和，並非持續吞吐不足的證據。

所以本次可接受為無損完整性與 RAM 證據，不能直接當成 writer backpressure 完全為零的證據。先前成功的 30 分鐘結果保留，同時記錄此次暴露的啟動風險。

## 最小原型修正

probe 0.1.16 增加明確 `Prepare()`：在 `clock.Restart()` 與第一個 capture request 前建立第一段、啟動 encoder、設定 pipe。`Write()` 若未準備則拒絕執行；第一幀不再負責首次 process 建立。watchdog 在真正寫入時才啟動，避免準備與 capture 之間誤判沒有進展。後續分段仍沿用既有路徑。

新增 `storage_prepare_ms`，以及每幀 `storage_open_ms`，讓下次可區分初始化與資料寫入。`no_free_slot` 額外保存 requested ticks、writer queue 與 outstanding readbacks，避免把 writer 造成的槽位耗盡誤認為 GPU 問題。驗證器另提示有 in-flight drops 時需檢查槽位壓力。

同一 C# writer 的 405 幀跨段測試與完整解碼核對通過。此回離線 preparation 12.95 ms，最長 Write 39.12 ms；本機原先也可能啟動很快，因此不聲稱這重現並排除了遊戲中的 1.07 秒停頓。初始化時序修正尚待遊戲首次啟動確認。

已備份並部署 0.1.16，FFV1、20 Hz、60 秒。需要重新啟動 DSP，載入場景後第一次按 Ctrl+F8 錄製，檢查 preparation、第一幀延遲、queue 與 slot drops。這是一分鐘的啟動確認，不替代既有 30 分鐘驗證。本票仍維持開啟，儲存方式尚未正式決議。
