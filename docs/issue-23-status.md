# Issue #23 示範資料交付核對

2026-09-25 完成 [Issue #23](https://github.com/JayWu07291/DSP_Dreamer/issues/23) 本批資料交付驗收。使用者確認六段失誤恢復示範，並明確回覆「同意工時例外」。六項條件依[本批修訂 2.0.1](../protocols/evaluation-v2.0.1-issue23.md)完成驗收；歷史工時與比例仍缺測，工時條款以核准例外處理，沒有改稱原要求全部實測達標。

使用者本日明確回覆人工工時「未紀錄」。初錄、補錄、正常流程與失誤恢復工時均記為未知，不以影片長度、完整回合時數、標註時間或原先預算代填，也不宣稱已達 3＋7 小時及 70／30 比例。

使用者在本對話逐段確認 R1–R6 均為「失誤後修正」，回答與來源另存於[人工確認紀錄](issue-23-recovery-confirmation.json)。後續工時例外核准另存於[修訂封印](../protocols/evaluation-v2.0.1-issue23.json)，適用本批 TrainingIndex 與 data freeze。沒有新增「必須錄到固定數量失敗回合」的要求，本票已無待使用者處理事項。

## 逐條核對

| #23 驗收條件 | 結果與證據 |
| --- | --- |
| 使用者人工示範、初錄分析後補錄及工時比例 | 依核准例外驗收。人工示範與按缺口補錄已有歷史證據；第八批診斷後沿固定 seed 順序補到第十八批。工時與比例永久保留未知，不宣稱符合原 3＋7 小時及 70／30。 |
| 四檔驗證、編譯與來源追溯，保留失敗／恢復 | 完成。正式資料沿用歷史驗證，24 份唯一錄製來源與 manifest checksum、COMPLETED、metadata 可追溯。保留 8 個無效回合及合法前綴；另有 6 段經使用者確認的失誤恢復示範。unknown_control 或 invalid 仍不當成遊戲失敗標註，片段內無效轉移維持原判定，人工示範不列為代理成果。 |
| 逐微任務 20／3／3 正例與全部覆蓋 | 通過。16 項微任務、3 個 split 的 48 個缺口皆為 0，完整統計見下表及機器報告。 |
| 重試、衍生片段不跨 split，隔離保留試驗 | 通過既有索引及本次身分核對。每份錄製僅保留一個正式衍生版本，按 group hash 重算 split 一致；40 份 development／final 的身分、group、seed、偏航與示範隔離。 |
| 凍結資料、split、artifact IDs、checksums 與協定 | 完成。沿用 9 月 24 日 data freeze 及基礎 v2 原 bytes，另附限定本批的 2.0.1 驗收修訂；未重抽 split 或改寫資料。正例 gate 已通過，沒有工時用盡而配額不足的待辦；未追認實際工時是否用盡。 |
| 分開工時、capture、完整回合、合法前綴及容量；模型判讀獨立 | 完成分列，人工工時缺測依核准例外保留未知。資料時數與容量見下文；容量不足停止新增、不自刪 evidence 的要求保留。模型品質仍 pending，training_authorized 與 offline_test_disclosure_authorized 均為 false。 |

## 覆蓋與時數

有效 capture 區間由 20 Hz 轉移表中 `valid=true` 的 `next_requested_ticks - requested_ticks` 加總，按各來源的 `ticks_frequency` 換算。它排除無效區間，不等於人工工時或錄製工作階段的牆鐘時間。全語料 355,853 張圖除以名目 20 Hz 得 4.942403 小時，這個名目值包含不可訓練部分，不作有效時數。

完整回合時數依 episode 起訖計算，可能包含個別掉幀。10 Hz 合法時數與無效回合內合法前綴沿用 #19 的凍結索引；前綴是合法時數的子集，不能重複加總。

| split | 有效完整回合 | 完整回合小時 | 有效 capture 區間小時 | 10 Hz 合法小時 | 其中合法前綴小時 |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 38 | 3.596296 | 3.823394 | 3.818813 | 0.245057 |
| validation | 4 | 0.380876 | 0.380326 | 0.380124 | 0 |
| offline-test | 5 | 0.475538 | 0.474425 | 0.474095 | 0 |

55 個回合記錄中，47 個為 success／valid，5 個 success／invalid，3 個沒有遊戲結果且 invalid。沒有完整有效的死亡、超時或無法繼續回合。8 個 invalid 均保留 unknown_control 原因，其中另有 2 個 reset、1 個 stopped；這些不能改列成有效的失敗示範。人工成功也不列為代理成果。

| split | 合法 64-step 起點 | relevant 起點 | progress-only 起點 | 等待視窗 | 非 active 完成 |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 117,160 | 42,403 | 72,933 | 33,111 | 323 |
| validation | 12,508 | 4,274 | 8,059 | 3,374 | 29 |
| offline-test | 15,463 | 5,555 | 9,704 | 4,045 | 33 |

下表每格依序為「active 啟用次數／active reward 正例不同回合數／非 active 完成數」。正例可來自合法前綴，因此可能多於完整有效回合。正例欄均為 live 資料；train 門檻 20，validation 與 offline-test 各 3。背景里程碑不列為微任務，因此上表的非 active 總數可高於這裡的加總。

| task_id | 微任務 | train | validation | offline-test |
| --- | --- | --- | --- | --- |
| 0 | start_dismantle | 46／20／0 | 4／3／0 | 5／3／0 |
| 1 | queue_research | 46／44／0 | 4／4／0 | 5／5／0 |
| 2 | queue_crafting | 45／43／1 | 4／4／0 | 5／5／0 |
| 3 | fuel_mecha | 37／36／8 | 4／4／0 | 5／5／0 |
| 4 | mine_copper | 37／37／6 | 4／4／0 | 5／5／0 |
| 5 | supply_metallurgy | 41／40／1 | 4／4／0 | 5／5／0 |
| 6 | place_iron_miner | 42／41／0 | 4／4／0 | 5／5／0 |
| 7 | place_copper_miner | 42／41／0 | 4／4／0 | 5／5／0 |
| 8 | supply_logistics | 41／41／0 | 4／4／0 | 5／5／0 |
| 9 | manual_smelting | 36／36／5 | 3／3／1 | 5／5／0 |
| 10 | supply_manufacturing | 41／39／0 | 4／4／0 | 5／5／0 |
| 11 | connect_smelters | 26／26／12 | 3／3／1 | 4／4／1 |
| 12 | supply_matrix_tech | 25／24／13 | 3／3／1 | 4／4／1 |
| 13 | setup_coil_line | 37／37／1 | 4／4／0 | 5／5／0 |
| 14 | setup_board_line | 26／26／12 | 4／4／0 | 5／5／0 |
| 15 | setup_lab | 38／38／0 | 4／4／0 | 5／5／0 |

## 凍結、容量與追溯

| 項目 | 身分 |
| --- | --- |
| TrainingIndex | `7301b78d7d5caaa63b2f600201c9c41d0890123bfe47f1d264cc1e7aa3b2ba21` |
| Data freeze | `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f` |
| Evaluation v2 | `40167e30d83bab5b60b19498ac45380899cd942d8f87fc347db37cae893a9e42` |
| 本批驗收修訂 2.0.1 | `8959ecfd5fa8826dfe570c2afc126fdd624d829282bfa90606280b5538e7e1d6` |

目前位置見 [data-catalog.json](data-catalog.json)，凍結原始路徑保留歷史身分。24 份 dataset 的 COMPLETED 宣告檔案長度加上 COMPLETED 本身，共 170,194,324,393 bytes，約 158.51 GiB；這不是本次重掃磁碟的實際占用量，也不包含封存 evidence、舊 dataset 或暫存峰值。

[#21 實測紀錄](https://github.com/JayWu07291/DSP_Dreamer/issues/21)為 evidence 18.9616、compiled 32.4131 GiB／capture 小時。規劃仍保留 #12 的保守容量與既有資料、編譯暫存、合併餘裕；不能用本次資料大小推論剩餘可錄工時。後續若恢復錄製，先按預定新增 capture 時數與當下磁碟空間檢查容量，不足即停新增，不自刪 evidence。本次沒有新增錄製或刪除資料。

歷史原始錄製與驗證報告保存在[封存](archive.md)。可從 Git 的固定版本查閱以下小型紀錄，無須解壓影片：

- [第八批缺口診斷](https://github.com/JayWu07291/DSP_Dreamer/blob/0f3a9be/docs/validation/coverage-diagnosis-batch8.md)記錄缺正例原因與後續固定順序。
- [第十八批收件](https://github.com/JayWu07291/DSP_Dreamer/blob/0f3a9be/docs/validation/recording-batch18.md)及[24 份來源總整合](https://github.com/JayWu07291/DSP_Dreamer/blob/0f3a9be/docs/validation/corpus-integration-20260921.md)記錄正式 Dataset／ModelView 驗證與最終配額。
- [資料與標註凍結](https://github.com/JayWu07291/DSP_Dreamer/blob/0f3a9be/docs/validation/evaluation-data-freeze-20260924.md)及 [#22 完成核對](issue-22-completion.md)保存協定、標註與模型品質的不同狀態。

## 重跑核對

在 repo 根目錄執行，輸出父目錄須已存在，檔案須尚不存在：

```powershell
.venv/Scripts/python.exe tools/verify-data-freeze.py --report tmp/issue23-audit.json
```

工具核對凍結檔案與程式 checksum、來源集合、COMPLETED、metadata、轉移表、錄製與 episode 唯一性、固定 split、40 份保留試驗隔離、索引配額算術，並輸出來源及全部覆蓋統計。這是搬移後的輕量核對，不重讀 RGB／原始錄影，不重算 active reward 或合法起點，不能取代正式 `TrainingIndex.open` 的完整內容驗證。實際開始載入資料時仍按[正式資料位置](data-layout.md)執行正式 loader。

本次機器報告為 [issue-23-audit.json](issue-23-audit.json)，保留當時狀態。恢復行為確認及工時例外核准均另存，舊報告的未檢查欄位不倒填。本批依修訂完成交付；模型判讀、訓練授權、recipe freeze、offline-test 揭露及試驗輸入設定核對各自維持既有待辦狀態。

## 本次驗證

真實資料的輕量核對通過；工具拒絕 checksum 已改動的索引，不產生報告，也拒絕覆寫既有報告，原檔 bytes 保持一致。mypy 檢查套件與工具共 19 檔通過。

工時例外核准後再次執行輕量核對，本機 `tmp/issue23-final-audit.json` 與原報告內容相同，artifact ID 仍為 `dd3a4a4cfdd98e6a82bd41ef315fe671c5e30dd6cc7953072b2919f383da9ffa`。此次只新增版本化驗收修訂及更新文件，沒有改動產品程式或重跑既有完整測試。

修訂封印、8 個來源檔案 checksum、六段人工回答關聯及核准原文均通過核對；7 個既有 evaluation 凍結檔案與 catalog checksum 一致。原協定、候選、人工確認及機器報告 bytes 與 `91574f6` 相同。修改修訂內授權欄位但未重算封印的副本遭拒絕，原始檔案未變。

完整 pytest 首輪為 128 passed、30 failed，失敗原因是整理後 .NET 測試專案缺少 `project.assets.json`。還原既有六個專案的依賴後，只重跑這 30 項，全部通過。合計 158 項通過，並非單輪 158 passed。兩輪 JUnit 位於本機 `tmp/issue23/pytest.xml`、`tmp/issue23/pytest-retry.xml`。沒有部署插件或改動遊戲設定。

## Standards

獨立複核未發現專案規範違反或需要處理的 code smell。工具實際核對範圍與報告一致；未重新計算 reward、未讀 RGB 的限制已明列。

## Spec

先前獨立複核未發現新增待修問題或範圍擴張。當時的兩類缺口已分別由使用者確認六段恢復行為，以及核准本批工時驗收例外處理。歷史工時缺測的事實仍保留。

工時例外修訂的收尾複核亦通過：Standards 0 項待修；Spec 0 項新增待修。本批資料交付不再有未核准的驗收缺口；模型 gate 仍獨立待驗證。
