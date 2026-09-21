# 第十八批錄製核對

2026-09-21，三回合全部為 success／valid，回合內沒有未知控制。每回合的 16 項微任務均取得合法 active 正例，本批不用重錄，也不預先安排第十九批。

| 回合 | 時長 | 有效轉移／全部轉移 |
| --- | --- | --- |
| 1 | 5 分 35.89 秒 | 6,712／6,717 |
| 2 | 5 分 55.74 秒 | 7,073／7,082 |
| 3 | 5 分 55.98 秒 | 7,115／7,118 |

Offline-test 開始拆解由 0／3 補到 3／3；熔爐自動接線、矩陣科技供料各由 1／3 補到 4／3；其餘 13 項各達 5／3。Train 與 validation 配額原已齊全。本批封存摘要與前批合計後，三個 split 的 16 項任務缺口全部為 0。

完整有效回合合計 train 38、validation 4、offline-test 5，共 47 回。配額表示資料覆蓋，不表示模型品質驗證通過，也不授權訓練。

## 指紋已恢復

本次 runtime fingerprint 為原核准的 `dda0773aa09e441e93120cefbf3e6dd3e5ae887a0760047ba78f8f92465c1dae`。遊戲輸入設定 SHA-256 恢復 `f993919fe80b1de22a462800b7a08170042aa39652a59e21435c65518e0a731d`，三回合使用原校正。先前音量變更造成的 F8 拒絕已解除，不需重新校正。

## 收件範圍與證據

來源為 `runs/live/63309a4e-b8ea-4c32-b21b-cef5e8b9ed83.source.evidence` 及相鄰 `.source.dataset`。本批原始檔 checksum、正式 Dataset／ModelView、單批 TrainingIndex、保留 trial 隔離及核准指紋均通過。收件耗時 86.48 秒，只開啟這次的新資料；原因診斷只讀 metadata、事件及轉移表，沒有檢視 offline-test 畫面或模型輸出。

證據保存在 `runs/catalog-v4/recording-review-20260921-batch18`，可追蹤摘要見 [機器可讀報告](recording-batch18.json)。新錄製沿用 plan index 17、bucket 90、seeds 230051／230052／230053；錄製器設定未再更動，action_catalog_v4、任務排程、協定及校正均不變。

## 接續工作

本批單獨收件後，依原定方式完成一次總索引整合，24 份唯一來源的總覆蓋 gate 通過，與累加報表一致。200 張 validation 圖片抽樣配額齊全，400 段影片候選已匯出，詳見 [語料整合與正式標註準備](corpus-integration-20260921.md)。第五批快照與歷史單批報告未覆寫，原始錄製未複製，日常收件仍不反覆重建語料。

資料凍結仍須綁定完成的人工標註；模型品質 gate 與後續閉迴路試驗尚未執行。
