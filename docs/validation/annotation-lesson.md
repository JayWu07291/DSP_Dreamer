# 兩題引導式標註練習

2026-09-16，依使用者同意，先以一張圖片、一段影片驗證「看指定位置，回答明確問題」是否容易使用。這是獨立練習，使用 `dsp-annotation-practice/1`，不轉成正式標註、不修改 evaluation-v1，不計入品質 gate。

圖片使用既有 validation 候選 R021，capture 400。框選左側物品提示列，分開問物品名稱與右側大數字；不推論數字是庫存或增減量。助理依原圖提出的示範為鐵塊、10，使用者仍可選看不清楚或保留不同答案。

影片使用候選 P002，原片 13.4–21.35 秒。歷史末圖為 19.8 秒，展示操作前、0.5 秒、1.5 秒，以及每 0.1 秒的 16 張無損原圖。問題限定為製造佇列最左側第一格有無物品圖示，不等同物品已製造完成。操作前／後放大圖同時顯示，另提供影片、半速、前後一格與時間滑桿。示範為空格→有物品圖示，操作類別為 UI。

示範答案由助理判讀，尚未經使用者確認。顯示示範的練習不能當作未受提示影響的正式標註；正式採用前仍須決定完整題目集、可辨識範圍、排除規則與評分準則。

## 執行

```powershell
.venv\Scripts\python.exe tools/export-annotation-lesson.py --workbench runs/schedule-v4/workbench --out runs/annotation-lesson-new --ffmpeg E:/SubtitleEdit-Windows-x64/SpeechToText/Purfview-Faster-Whisper-XXL/ffmpeg.exe
.venv\Scripts\python.exe tools/serve-annotation-workbench.py runs/annotation-lesson-new 8827
```

本次交付目錄是 `runs/annotation-lesson-v3`，[練習頁](http://127.0.0.1:8827/)。前兩版保留為本次試用紀錄。匯出器固定核對原 workbench receipt 與選用素材 checksum，拒絕換包、覆寫或路徑重疊。直接複製已驗證的無損 PNG，只將既有壓縮導覽影片裁成短片。

交付 artifact ID：`4a1f488ada3a9d1bd5ca3f1d6a233f6e83ea95e12b078082af5a8aae4329c130`。20 個輸出檔案均完成 checksum 核對，頁面與本次提交的 HTML 一致。

先前嘗試直接讀資料集時，numcodecs DLL 曾被 Windows 應用程式控制阻擋，沙箱外重試亦出現另一 codec 的載入錯誤。練習所需原圖已全數存在，因此改用 Python 標準函式庫、既有 contract checksum 與固定 FFmpeg，不必新增依賴；沒有變更系統安全設定。之後完整回歸可正常執行並通過，不把這次練習匯出當成底層 DLL 問題的修復。

## 驗證

- 原始圖片與 16 個影格均與原匯出包 checksum 相符。
- `node tests/check-annotation-lesson.cjs`：填答格式、不確定答案、逐格邊界與未確認修改阻止匯出通過。
- mypy 2 個來源檔通過；完整 pytest 150 項通過，167.97 秒。
- 瀏覽器確認圖片放大、正常／不確定填答、前後對照、0.5 秒對應影片 6.9 秒、播放結束定位第 15 格。
- 匯出 JSON 的 `status=practice`、`training_authorized=false`、來源與回答皆已核對。瀏覽器下載事件沒有回傳檔案，故增加可見 JSON 與複製備份，複製實測成功。
- 回答只存在分頁記憶體；修改後須重新確認，離開前有未備份提醒。原頁與舊草稿保留。

Standards 與 Spec 獨立複核均無剩餘阻擋。使用者是否能順利理解並回答仍待實際試用，沒有將瀏覽器測試當成人工驗收。
