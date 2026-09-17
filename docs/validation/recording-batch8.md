# 第八批錄製核對

2026-09-17 後續更新：第九批改為先錄 **一回合** 驗證開局順序。請依 [任務正例缺口診斷](coverage-diagnosis-batch8.md) 操作，原先的兩回合安排已取代。下方保留第八批資料核對與第九批設定紀錄。

2026-09-17，僅驗證新錄製 `runs/live/a6b488d5-11b1-4545-b984-1467b4037311.source.evidence` 及相鄰 `.source.dataset`。Dataset artifact 為 `6f2f5ddd-59b1-47ca-b6bd-d99000fa5d6d`，共 12,898 張影像、12,897 個轉移。

| 回合 | 時長 | 遊戲結果／資料判定 | 有效轉移 |
| --- | --- | --- | --- |
| 第一回合 | 5 分 31 秒 | success／valid，完整可用 | 6,615 |
| 第二回合 | 5 分 14 秒 | success／valid，完整可用 | 6,272 |

兩回合內均無未知控制，不需重錄。原始三個檔案 checksum、正式 Dataset／ModelView、單批 TrainingIndex 與保留試驗隔離檢查通過。本批使用 demonstration plan index 7、seeds 230021／230022／230023，manifest `c05c41ad6c106ed0d7b0454d84c5fb1a37c451f736bb06be99ed6558c5381f77`、bucket 8，屬於 train。

## 單批收件

驗證與單批索引共 34.95 秒，只開啟本批 dataset；歷史 Dataset／ModelView 開啟數為 0，未讀取舊 RGB、未重建總索引或評估包。沿用第七批封存報告並核對新錄製與 episode 未重複，共保留 12 份來源身分。

單批索引 `13fa1eca9455c561904320506b4567fa629a008268ef3f15c13770d6a60796fa` 位於 `runs/catalog-v4/recording-review-20260917-batch8/batch-index.json`。本批 task 1–10、13–15 各有 2 回合法 active 正例，task 12 有 1 回，task 0、11 為 0；非 active 完成不補入此計數。

封存報告合計完整有效回合為 train 20、validation 1、offline-test 2。完整回合數不是各微任務正例數，也不表示總覆蓋 gate 已通過；此合計不取代重建後的總索引。

最新完整總索引仍為截至第五批的 `df0c6c00e75febf2e528152f4d1a38abf11f657d937b56f1ef206b63036a7814`，評估輸入包仍為 `2996a261c8e3bd8545db6bcd754b552e6acf0ce12df495fdbcf347e28af267a0`。第六至八批列入待整合來源，既有 baseline、抽樣與標註包均未重建。來源清單、前次報告連結、單批統計及套用收據見 [機器可讀報告](recording-batch8.json)。資料未凍結，未授權訓練。

後續繼續只驗證新錄製、保存單批索引與報告；正式資料凍結或有明確需要時，再統一重建總索引與評估輸入。

## 第九批設定

已按原定順序套用 index 8，seeds 230024／230025／230026，manifest `8f8fd274a2df44c1fb8475f7daa4398121284c18dc720857ef669aec50dcfca2`，bucket 12 屬於 train。只修改三個 seeds，原設定已備份並核對套用後內容。存檔、輸入設定、錄製器 DLL、指紋、校正及保留試驗隔離均通過核對。動作空間保持 `action_catalog_v4`／21 維，Diagnostics 關閉。

接著依 [任務正例缺口診斷](coverage-diagnosis-batch8.md) 先錄第九批一回合：F8 開始，登陸艙拆完再開科技樹，其餘沿用採礦優先流程；成功後 F8 結束並等發布完成。這次不按 F9 接第二回合，無須重啟或重新校正。
