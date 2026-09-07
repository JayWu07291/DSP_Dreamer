# 首次啟動確認，2026-09-07

run `20260906T162147Z`，probe 0.1.16。六段、1,198 幀完整解碼與 RGBA hash、索引、順序一致，無 partial。本次重驗也通過，verification 報告保留時間戳，不覆寫前次驗證。

- 60.043 秒，有效 19.9524 Hz；2 次 scheduler gap，掉幀率 0.1667%。
- in-flight drops、GPU readback error、writer drops 均為零，writer queue 最高 1。
- storage_prepare_ms=16.1297，發生在 capture clock 啟動前。
- 第一幀 storage_open_ms=0，storage_write_ms=9.8872；全 run 最長 Write=52.3102 ms，最長 finalize=23.4266 ms。
- FFmpeg peak working set 77,406,208 bytes，73.82 MiB；DSP RSS 取樣峰值約 4.08 GiB。

本次未重現前次 1.07 秒首次 Write 停頓，也未再耗盡 capture slots。這支持初始化時序修正，但只是一次遊戲首次啟動確認，不保證所有冷快取、系統負載與安全軟體條件都無停頓。它不取代先前 30 分鐘測試；正式錄製器仍需完整端到端驗收。

舊總判定因短測缺拆除事件與控制注入而為 inconclusive_or_fail。這些不是本次啟動確認目的，原始 summary 保持不變。
