# Issue #19 固定 split、訓練片段與資料覆蓋

## 範圍與前置證據

2026-09-11 實作固定 split、合法 sequence 索引、第二階段 50／50 抽樣與覆蓋報告。沿用 #16 的進度判定及 #18 的 `action_catalog_v3`／20 維模型視圖，不將 issue 本文殘留的 v2 名稱當成回退要求。已核對兩票 GitHub 結案紀錄與本機驗收文件；#16 的完整人工流程及 #18 的離線資料驗證通過，不代表長程資源、訓練品質或資料覆蓋 gate 通過。

前置來源為 [#18 完整流程](issue-18-full-flow-live.json)與[重試／跨回合](issue-18-retry-live.json)驗收的兩份 `/4` dataset。此次透過正式 loader 再驗證全部檔案 checksum、RGB、動作、lifecycle、事件與進度標籤，沒有修改來源。

## 實作與驗證方式

`TrainingIndex` 與 `python -m dsp_dreamer index` 接受完整 datasets 和必要用途登錄檔。登錄檔補足現有 trial manifest 沒有的用途資訊；任何未登錄、同 manifest 不同 split group、重複來源或回合都拒收。development／final 保留整組，即使同組有 demonstration 也不進離線 split。固定 hash 使用 SHA-256 全部位元取模 100，範圍 0–79／80–89／90–99；沒有重新抽 split 或按任務補正例的入口。

重用模型視圖的合法起點，使用累計計數枚舉全部含完成的起點，只有 `progress_fact` 的另列。視窗可以跨提示，不能跨回合、gap 或無效區間。合法前綴可含故障前完成的正例；正例必須在至少一條合法完整 sequence 內，按 episode 去重。模型動作 ambiguous 或不足兩個原始轉移的視窗不計訓練正例，非 active 完成不冒充 scalar reward。

偶數 batch 各半從 uniform／relevant 起點池均勻有放回抽樣。Uniform 只啟用 dynamics loss mask，relevant 只啟用 policy／reward loss masks；共同排除 burn-in，索引抽樣不接受 padding。空池拒絕，不降級比例。抽樣介面可供補錄前檢查，但訓練器必須另查 `coverage_gate_passed`；本票沒有啟動訓練。

`tests/test_training_index.py` 經合成錄製、FFV1 四檔、compiler、模型視圖及索引，核對重試、非 active 完成、等待、跨提示、progress-only、故障、gap、短片段、保留組、三種固定 split、輸入次序及抽樣 determinism、mask、checksum 損壞及覆寫拒絕。正式介面重用 #12 已確認的整合測試入口，沒有 mock 內部 helper。

## 真實資料結果

兩份示範的 `split_group_id` 相同，hash bucket 為 87，全部屬 validation。保留真實分組結果，不為補足 train 正例重抽。

| 資料 | 合法 64-step 起點 | relevant 起點 | progress-only 起點 | 跨提示起點 |
| --- | ---: | ---: | ---: | ---: |
| #16 完整流程 | 3,303 | 1,037 | 2,237 | 777 |
| #15 重試／跨回合 | 1,456 | 522 | 750 | 394 |
| 合計 | 4,759 | 1,559 | 2,987 | 1,171 |

Validation 有 1 個有效完整回合，共 0.1000832672 小時；所有合法模型視窗合計 0.1462264448 小時，其中無效／不完整回合的合法前綴為 0.0463076985 小時。這些時數不以重疊 sequence 重複累加。有效等待視窗 1,373 個；非 active 完成共 16 個，含微任務與背景里程碑。

以下為 validation 中可落在合法 64-step sequence 的 active scalar reward 不同回合數。train 每個微任務仍缺 20 回合，offline-test 每個微任務仍缺 3 回合。

| 微任務 | validation 正例回合 | 缺口 |
| --- | ---: | ---: |
| start_dismantle | 0 | 3 |
| queue_research | 3 | 0 |
| queue_crafting | 2 | 1 |
| fuel_mecha | 2 | 1 |
| mine_copper | 2 | 1 |
| supply_metallurgy | 1 | 2 |
| place_iron_miner | 0 | 3 |
| place_copper_miner | 0 | 3 |
| supply_logistics | 1 | 2 |
| manual_smelting | 0 | 3 |
| supply_manufacturing | 1 | 2 |
| connect_smelters | 0 | 3 |
| supply_matrix_tech | 0 | 3 |
| setup_coil_line | 1 | 2 |
| setup_board_line | 1 | 2 |
| setup_lab | 1 | 2 |

完成完整流程不代表每個完成都是 active reward 正例。部分微任務非 active 時已完成，也有正例落在無法形成 64-step 合法片段的短區間；原始完成仍留在 dataset。報告的正式 gate 只計實機正例，合成測試不補足門檻。目前只有 validation 的 queue_research 達標，整體 `coverage_gate_passed=false`，依賴此 gate 的訓練階段仍不可開始。

## 可重跑證據

[用途登錄檔](issue-19-registry.json)、[完整索引與覆蓋](issue-19-live-index.json)、[獨立核對結果](issue-19-live-verification-v2.json)保存版本、來源、artifact ID 與 checksum。索引的 `artifact_id` 對整份內容計算 SHA-256，欄位本身除外；來源另含 COMPLETED、原始 manifest 與模型視圖契約。重新開啟會從正式來源重建並逐內容比對。

驗證工具用逐起點逐視窗的方式獨立核對全部合法起點與兩種子集，另確認 1,171 個跨提示起點仍合法，包含 10 Hz 視窗內及最後 next observation 的提示切換；實際讀取兩條 64-step RGB batch，檢查來源、padding／burn-in 及三種 loss masks。反轉資料來源次序重建，輸出完全相同，來源 COMPLETED 前後 checksum 相同。大型來源留在本機，不上傳 GitHub。

[初次核對結果](issue-19-live-verification.json)保留作修正紀錄。該版只比較視窗起始 task，漏算 15 個跨提示起點；Spec 審查發現後改查每個視窗的 `task_switches`，並加入 CLI 整合回歸測試。合法／relevant／progress 起點、覆蓋報告與索引 checksum 不受影響；跨提示計數以 v2 核對結果為準。

以下輸出路徑須尚不存在：

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer index --source runs/live/issue18-full-flow-v4 runs/live/issue18-retry-v4 --registry docs/validation/issue-19-registry.json --length 64 --out runs/issue19-index-rerun.json
.\.venv\Scripts\python.exe tools/verify-training-index.py --source runs/live/issue18-full-flow-v4 runs/live/issue18-retry-v4 --index runs/issue19-index-rerun.json --report runs/issue19-verification-rerun.json
.\.venv\Scripts\python.exe -m pytest tests/test_training_index.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer tools/verify-training-index.py
```

本票只驗收資料索引與計數，沒有訓練模型，也沒有宣稱十小時完整 loader 的記憶體或吞吐已通過 #21。

## 自動化檢查

2026-09-11 審查修正後完整 pytest 共 114 項通過，耗時 134.18 秒，本機 JUnit 紀錄為 `tmp/issue19-final-tests.xml`。新增索引整合測試 5 項通過；mypy 檢查套件與真實驗證工具共 15 個檔案通過。`git diff --check` 通過，CLI 的 `index --help` 與真實資料匯出均可執行。第一次完整測試亦為 114 項通過，耗時 140.23 秒，紀錄保留於 `tmp/issue19-tests.xml`。

## Standards

以 `42d156244fc12f2e18fae423d65b9125be610139` 為基準，由獨立 agent 審查 AGENTS.md、domain 規則、CONTEXT.md、Ponytail 與 code-review smell baseline。原有兩項 findings：記憶體索引缺少 ceiling 註解，以及覆蓋門檻 mapping 名稱不明確。已補上 `ponytail:` 註解，記錄 O(windows) RAM 及 #21 未過時的磁碟索引升級路徑；`SPLITS` 已改為 `COVERAGE_REQUIREMENTS`。原審查 agent 複核無剩餘問題，修正後 5 項整合測試與 mypy 15 檔再次通過。

## Spec

獨立 agent 發現跨提示驗證漏看 10 Hz 視窗內及最後 next observation 的切換，同時造成驗收計數偏低。已改查保留完整切換的 `task_switches`；新增回歸案例在舊工具得到 2、修正後得到預期 4 個跨提示起點，原審查 agent 已複核通過。其餘固定 split、隔離、抽樣、統計欄位及來源 checksum 未發現明確規格違反，也沒有範圍擴張。

Standards 兩項已解決，Spec 兩項同源問題已解決，兩軸均無剩餘 findings。
