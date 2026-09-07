# 遊戲觸發與無視窗 worker 修正

此錄製證明 0.1.17 的遊戲停止 hook 已啟動背景 worker，但第一次自動合併失敗。來源已驗證完成，remux 啟動時 Python 繼承遊戲提供的無效 stdout handle，出現 `WinError 6`，未发布 manifest，也沒有清理來源。原始錯誤見 [automatic-error.txt](automatic-error.txt)。

以實際 worker 加 Windows `SetStdHandle` 建立回歸測試。僅將 stdout 設為無效即可重現相同的 remux 啟動錯誤。將三個 console handles 都設為無效則也暴露版本查詢對 stdin 的繼承。修正為所有 worker 使用的 FFmpeg 呼叫明確設定 stdin／stdout／stderr，並使用 CREATE_NO_WINDOW。版本查詢、來源 decode、remux、最終 decode 及 seek 均不依賴父程序 console handles。

[修正前](headless-before.json)失敗；[修正後](headless-after.json)在三個 handles 皆無效時，完整重驗、合併、發布、清理均成功，輸出恰剩四檔。測試使用此錄製的 workspace 副本。

已備份並更新部署的兩個 Python 檔，DLL 仍為 0.1.17，不需關閉遊戲或重載 DLL。備份在 `out/headless-worker-backup-20260907/`。隨後依使用者既有的自動清理授權，重試這次原始 run：

- 1,199 幀 RGBA hashes、順序與 20 fps 播放 PTS 全部一致，12 個 seek 點通過。
- 6,130 筆事件 byte-identical；整併索引回讀通過。
- MKV 265,502,324 bytes，remux 約 0.41 秒。
- 重新讀取最終 manifest 並核對三個資料檔 SHA-256 通過。
- run 根目錄只剩 `recording.mkv`、`events.ndjson`、`frames.ndjson`、`manifest.json`，暫存段與工作目錄均已清理。

詳細見 [final-verification.json](final-verification.json)。原始 summary 的舊驗收仍為 inconclusive，因本短測没有涵蓋完整微任務及注入測試；新 manifest 才是此次合併驗證狀態。

遊戲自動觸發已有實機證據；修正版無效 handle 情境已有完整回歸證據。本次最終完成由修復後重試取得，不稱為修正版的新一輪遊戲自動成功。互動式播放器與斷電持久性仍未測試。
