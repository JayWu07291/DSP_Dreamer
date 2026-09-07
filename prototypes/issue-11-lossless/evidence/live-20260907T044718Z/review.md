# 修正版自動合併與清理實機確認

20260907T044718Z 為修正背景子程序 console handles 後的新遊戲錄製。收到路徑時已只有四個最終檔案，沒有執行人工 finalize 或清理。BepInEx LogOutput.log 對此 run 記錄「合併與驗證完成，已清理暫存分段」，證實遊戲 hook、worker、驗證及清理完整自動完成。

- 60.087 秒、1,199 幀，19.9543 Hz；scheduler missed 1 幀，in-flight／readback／writer 掉幀皆 0，queue 最高 2。
- 自動驗證的逐幀 RGBA、索引回讀、播放 PTS 及 12 個 seek 點皆通過。
- 6,122 筆事件 byte-identical。單一 MKV 239,853,558 bytes，remux 約 0.40 秒。
- 本次唯讀檢查重新核對三個資料檔 SHA-256，再獨立完整解碼 1,199 幀，逐幀 hash 與 20 fps PTS 全部一致。
- 根目錄只剩 recording.mkv、events.ndjson、frames.ndjson、manifest.json，沒有 segment、鎖檔或工作目錄。

見 [verification.json](verification.json)及[遊戲完成紀錄](completion-log.txt)。來源 summary 的舊 metrics_verdict 因短測缺少完整微任務與注入操作而 inconclusive，不能視為合併驗證失敗。這次確認一分鐘實機自動流程成功，不取代正式版長程、斷電與 compiler 驗收。
