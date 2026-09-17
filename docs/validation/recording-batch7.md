# 第七批錄製核對

2026-09-17，僅驗證新錄製 `runs/live/e8c6bbab-ea55-4a12-94f4-a26d8d4352bf.source.evidence` 及相鄰 `.source.dataset`。Dataset artifact 為 `2f1bd38a-1399-45d6-96d3-80fba342e777`，共 13,045 張影像、13,044 個轉移。

| 回合 | 時長 | 遊戲結果／資料判定 | 有效轉移 |
| --- | --- | --- | --- |
| 第一回合 | 5 分 28 秒 | success／valid，完整可用 | 6,546 |
| 第二回合 | 5 分 25 秒 | success／valid，完整可用 | 6,491 |

兩回合內均無未知控制，不需重錄。原始三個檔案 checksum、正式 Dataset／ModelView、單批 TrainingIndex 與保留試驗隔離檢查通過。本批使用 demonstration plan index 6、seeds 230018／230019／230020，manifest `0d10cffd7419f9082bb1b2ad572b911c6796a208255777fff47d7b5d58615d9b`、bucket 56，屬於 train。

## 單批收件

驗證與單批索引共 34.93 秒，只開啟本批 dataset；歷史 Dataset／ModelView 開啟數為 0，未讀取舊 RGB、未重建總索引或評估包。沿用第六批封存報告的來源身分清單並核對新錄製與 episode 未重複，共保留 11 份來源身分。

單批索引 `98a6977b9a8ca2e7bee666ac5c6710431a7cac61dd514d04b5de047801644a3f` 位於 `runs/catalog-v4/recording-review-20260917-batch7/batch-index.json`。本批 task 1–10、13、15 各有 2 回合法 active 正例，task 12、14 各 1 回，task 0、11 為 0；非 active 完成不補入此計數。

封存報告合計完整有效回合為 train 18、validation 1、offline-test 2。這是既有報告加上本批的去重合計，並非重新建立的總索引或總覆蓋 gate。

最新完整總索引仍為截至第五批的 `df0c6c00e75febf2e528152f4d1a38abf11f657d937b56f1ef206b63036a7814`，評估輸入包仍為 `2996a261c8e3bd8545db6bcd754b552e6acf0ce12df495fdbcf347e28af267a0`。第六、七批列入待整合來源，既有 baseline、抽樣與標註包均未重建。來源清單、前次報告連結、單批統計與套用收據見 [機器可讀報告](recording-batch7.json)。資料未凍結，未授權訓練。

後續繼續只驗證新錄製、保存單批索引與報告；正式資料凍結或有明確需要時，再統一重建總索引與評估輸入。

## 第八批設定

已按原定順序套用 index 7，seeds 230021／230022／230023，manifest `c05c41ad6c106ed0d7b0454d84c5fb1a37c451f736bb06be99ed6558c5381f77`，bucket 8 屬於 train。只修改三個 seeds，原設定已備份並核對套用後內容。存檔、輸入設定、錄製器 DLL、指紋、校正及保留試驗隔離均通過核對。動作空間保持 `action_catalog_v4`／21 維，Diagnostics 關閉。

接著錄第八批兩回合：F8 開始，第一回合成功後 F9 重載，第二回合成功後 F8 結束並等發布完成。沿用採礦優先流程，無須重啟或重新校正。
