# 第六批錄製核對

2026-09-17，僅驗證本批新錄製 `runs/live/5a3c4287-8576-489f-8b64-c10a55dd5fe3.source.evidence` 及相鄰 `.source.dataset`。Dataset artifact 為 `0bac1a1e-8c2f-4dac-99d7-e69c906dc355`，共 13,751 張影像、13,750 個轉移。

| 回合 | 時長 | 遊戲結果／資料判定 | 有效轉移 |
| --- | --- | --- | --- |
| 第一回合 | 5 分 25 秒 | success／valid，完整可用 | 6,501 |
| 第二回合 | 6 分 3 秒 | success／valid，完整可用 | 7,239 |

兩回合內均無未知控制，不需重錄。原始三個檔案 checksum、正式 Dataset／ModelView、單批 TrainingIndex 及保留試驗隔離檢查通過。本批使用 demonstration plan index 5、seeds 230015／230016／230017，manifest `2a849a6f38c3d11ab76b7e8fd33300518c364d052d1869631b0b5c91d3803c81`、bucket 31，屬於 train。

## 單批收件

驗證與單批索引共 35.93 秒，只開啟這一份新 dataset。歷史 Dataset／ModelView 開啟數為 0，未讀取舊 RGB、未重建全語料索引或評估包。只讀既有封存報告核對來源、錄製與 episode 身分，確認沒有重複計數。

單批索引 `f7a0ea3fadaa1e36288d8e3be961df55ef8885e7b7a55839e3810eb9c5295fc6` 存於 `runs/catalog-v4/recording-review-20260917-batch6/batch-index.json`。本批 task 1–10、12、15 各有 2 回合法 active 正例；task 11、13 各 1 回；task 0、14 為 0。非 active 完成不補入此計數。

依第五批封存報告加上本批兩個不重複完整有效回合，累積紀錄為 train 16、validation 1、offline-test 2。這是報告合計，並非重建後的總索引或總覆蓋 gate。

最新完整總索引仍為截至第五批的 `df0c6c00e75febf2e528152f4d1a38abf11f657d937b56f1ef206b63036a7814`，評估輸入包仍為 `2996a261c8e3bd8545db6bcd754b552e6acf0ce12df495fdbcf347e28af267a0`。第六批列入待整合來源；既有 baseline、抽樣與標註包沒有更新，也不宣稱已反映本批。完整來源清單、去重身分、單批統計及設定收據見 [機器可讀報告](recording-batch6.json)。資料未凍結，未授權訓練。

後續繼續採 [第五批報告所定收件方式](recording-batch5.md)：只驗證新錄製並保存單批索引與報告；沿用舊報告，將新來源累積到待整合清單。正式資料凍結或有明確需要時，再統一重建總索引與評估輸入。

## 第七批設定

已按原定順序套用 index 6，seeds 230018／230019／230020，manifest `0d10cffd7419f9082bb1b2ad572b911c6796a208255777fff47d7b5d58615d9b`，bucket 56 屬於 train。只修改三個 seeds，原設定已備份並核對套用後內容。存檔、輸入設定、錄製器 DLL、指紋、校正及保留 trial 隔離均通過核對。動作空間保持 `action_catalog_v4`／21 維，Diagnostics 關閉。

接著錄第七批兩回合：F8 開始，第一回合成功後 F9 重載，第二回合成功後 F8 結束並等發布完成。沿用採礦優先流程，無須重啟或重新校正。
