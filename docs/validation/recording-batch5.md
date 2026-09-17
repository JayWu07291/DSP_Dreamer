# 第五批錄製核對

2026-09-17，使用者提交兩個連續回合。來源為 `runs/live/52b83978-c47b-42b5-a191-1d86b26c8f03.source.evidence`，正式資料集位於相鄰 `.source.dataset`，artifact 為 `21a738c8-39fe-41cb-87d9-e0d25133e7d3`。共 13,272 張影像、13,271 個轉移，原始三個檔案 checksum 與正式 Dataset／ModelView 讀回均通過。

| 回合 | 資料判定 | 有效轉移 |
| --- | --- | --- |
| 第一回合 | valid，完整回合可用 | 6,538 |
| 第二回合 | valid，完整回合可用 | 6,720 |

兩回合內均未發現未知控制。Capture 6543 的跨回合區間包含 F9，既有規則已將此重載區間標為無效；它沒有使任何一個回合失效，也不納入合法 sequence。原始輸入與邊界紀錄全部保留。

本批使用 demonstration plan index 4，seeds 為 230012／230013／230014，manifest `7eb4006cda9692896ebd498712814c3a75e237fdbfce9c40980f70ca25df889b`、bucket 93，固定屬於 offline-test。核對範圍限契約、資料有效性與標籤覆蓋計數，未判讀測試畫面或計算模型分數。`action_catalog_v4` 的 21 維控制、progress version 4、human 模式、已核准指紋與校正保持一致，Diagnostics 關閉。

## 索引與隔離

本次九份來源共 152,636 張影像完成讀回。完整有效回合為 train 14、validation 1、offline-test 2；本批只增加 offline-test 的 2 回。逐任務標籤覆蓋見 [機器可讀報告](recording-batch5.json)，覆蓋 gate 仍未通過。

全語料索引 ID 為 `df0c6c00e75febf2e528152f4d1a38abf11f657d937b56f1ef206b63036a7814`，評估輸入包 ID 為 `2996a261c8e3bd8545db6bcd754b552e6acf0ce12df495fdbcf347e28af267a0`，位於 `runs/catalog-v4/recording-review-20260917-batch5`。舊八份來源條目、train／validation 統計與 train-only baseline 均與第四批後相同；validation 重建名單相同，第五批沒有進入重建抽樣。沒有計算或揭露模型結果。

既有人工草稿保留，逐任務重建配額仍缺 32 張，預測四類各 50 段及完整標註仍待處理。資料尚未凍結，也未授權訓練。

## 後續收件不再逐批掃描歷史影像

使用者指出每批重讀歷史錄製浪費時間與磁碟 I/O。原因是收件腳本每次把所有 `source_paths` 傳給 `TrainingIndex`，它逐一呼叫 `open_model_view → open_dataset`，重新驗證檔案 checksum、事件、轉移及全部 RGB。第五批原本只需收件一份，卻又完整讀了八份舊來源。

從第六批起，日常收件只將新錄製傳入既有 `index` 指令，保存該批的 `batch-index.json`、來源身分、checksum、回合有效性及標籤覆蓋報告。舊批次引用已保存的報告，累積來源清單須避免同一錄製或衍生資料重複計數。只讀先前小型報告或必要 metadata 核對身分，不重新打開舊 ModelView，不掃描歷史 RGB，也不每批重跑 `prepare_evaluation`。

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer index --source 'runs/live/NEW.source.dataset' --registry runs/issue22-preparation/recording-registry.json --length 64 --out 'runs/catalog-v4/NEW-REVIEW/batch-index.json'
```

以上 `NEW` 路徑須替換為本批實際產物，輸出父目錄須先存在。單批索引不是全語料索引；本頁所列總索引只涵蓋截至第五批的資料，後續單批報告不可冒稱已更新總索引或通過總覆蓋 gate。示範收齊、正式凍結資料或有明確需要時，再統一重建全語料索引與評估輸入。若來源或契約改變，另驗受影響資料。原有 loader 的完整校驗與最終凍結門檻不變；沒有新增快取或跳過驗證的開關。

## 第六批設定

已按原計畫套用 index 5，seeds 為 230015／230016／230017，manifest `2a849a6f38c3d11ab76b7e8fd33300518c364d052d1869631b0b5c91d3803c81`，bucket 31 屬於 train。已核對保留試驗隔離、存檔、輸入設定、DLL、指紋及既有校正，並備份及讀回設定；只修改三個 seeds。

第五批不需重錄，下一步錄第六批兩回合：F8 開始，第一回合成功後 F9 重載，第二回合成功後 F8 結束並等發布完成。無須重啟或重新校正，沿用採礦優先安排。
