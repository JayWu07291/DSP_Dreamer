# Issue #22 評估協定凍結

2026-09-24 更新：資料覆蓋已通過，人工確認已接入並完成補錄後的資料與標註凍結。正式名單為重建 200 張、預測四類各 50 段，詳見 [資料與人工標註凍結報告](evaluation-data-freeze-20260924.md)。目前沒有需要補標或補錄的工作。下文保留 9 月 14 日的 v1 歷史狀態；現行為 v2，模型品質仍待驗證，未授權訓練。

本票完成補錄前的可重跑協定、抽樣準備、baseline 演算法、版本與試驗隔離。人工分類、標註、判讀及正式模型評估均未執行。#19 已結案只代表索引／缺口計數通過，資料覆蓋 gate 仍未過；本票沒有啟動訓練或授權跨過任何 gate。

## 交付與契約

[協定](../../protocols/evaluation-v1.md)逐項固定 #12／#8／#7 的重建、動作條件預測、reward、policy 門檻、分母、缺測處理、對照、LPIPS 設定、標註格式、受影響區域、sampling／generation seeds、選模及 offline-test 揭露順序。使用 #18／#19 已驗收的 `action_catalog_v3`。版本與凍結時間見 [JSON](../../protocols/evaluation-v1.json)，其 checksum 綁定協定、工具及 trial manifests；Git 固定這些檔案 LF，避免 checkout 改變原始位元組。

[40 份 trial manifests](../../protocols/evaluation-trials-v1.json)保存 Starting Save、世界種子 97807908、1280×720 遊戲畫面及既有 UI 設定 hash，模型 RGB 仍為 640×360。10 development／30 final 使用不同的 mecha、camera、policy seeds。Windows PowerShell 5.1 在 .NET Framework 上使用錄製器既有 C# Json encoder，產生相同的偏航及 manifest_id；Python 測試逐內容重建比對全部 40 份。這證明格式與固定亂數相容，不代表這些 trial 已在 DSP 執行。

[用途登錄檔](../../protocols/evaluation-registry-v1.json)保留 #19 的示範組並加上 40 份保留試驗。驗證工具拒絕 development／final 身分或數量變更、示範共用保留組／seed／偏航，以及錄製的 trial 與固定內容不符。兩候選必須讀同一 development 清單；final 不進選模。後續補錄另存新增示範登錄的 registry 版本，保留 40 份試驗不變，資料凍結再綁定新 index_id。

## 現有資料的實際缺口

以 #18 已驗收的完整流程與重試／跨回合兩份實機 `/4` dataset 重驗 checksum、compiler／loader 與來源，建立包含保留組的新索引。抽樣規則固定，來源未修改。

| 項目 | 實際狀態 |
| --- | --- |
| 重建候選 | 200 張不同來源觀測；尚未滿足所有 task quota |
| 每 task 至少 10 張 | task 6、7、9、11、12 各缺 10 張，task 14 缺 2 張 |
| 關鍵項目、主要 UI 覆蓋 | 尚未人工標註／確認，pending |
| 預測 200 段 | 尚未人工分類及標定區域，四類各缺 50 段 |
| Train baseline | 兩份來源均屬 validation，沒有 train 統計，insufficient_evidence |
| 資料覆蓋 | 沿用逐 split 20／3／3 正例要求，未通過 |
| 模型品質 | 未測，不能算通過 |
| 補錄後資料／split 凍結 | 尚未執行 |
| Offline-test／final 模型結果 | 未執行、未揭露 |

來源反序重跑的名單、分組與缺額相同。審查期間曾修訂協定及工具 hash，因此不同修訂的輸入包有不同 protocol_id，不把它們當成相同 artifact。[評估輸入包](issue-22-live-inputs.json)保存最終實際名單、逐 task 缺額、來源 model_view／COMPLETED hash、index_id、protocol_id、baseline 來源與 `training_authorized=false`。其 200 張只供待標註準備，不能宣稱 #22 所需的完整重建評估集已驗收。

## 重跑

輸出路徑必須不存在。命令會重驗整份來源，可能耗時數分鐘。

```powershell
.\.venv\Scripts\python.exe tools/prepare-evaluation.py --source runs/live/issue18-full-flow-v4 runs/live/issue18-retry-v4 --registry protocols/evaluation-registry-v1.json --out runs/issue22-inputs.json
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_protocol.py -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer tools/prepare-evaluation.py
.\.venv\Scripts\python.exe -m pytest -q
```

預測人工分類恢復後，依協定的 `dsp-prediction-candidates/1` 格式封存並傳入 `--candidates`。工具只接受合法 validation 79-step 起點，不能跨 gap／fault／回合；採樣前三類及等待各 50，凍結同 task／同類循環打亂 donor、前 5 步動作差異與共用生成 seed。單一 stratum 或相同動作不冒充有效打亂。

工具尚未執行 LPIPS、模型 forward 或人工評分，本票固定的是它們的協定。人工工時暫緩，不能藉合成測試補足資料／模型證據。`authorize_test_disclosure` 僅檢查明示的凍結 artifact 連結、內容 hash、時間順序及未看 test/final 的聲明，不能保證外部人員未看結果，也不授權訓練。

## 自動化檢查

2026-09-14 完整 pytest 143 項通過，耗時 151.79 秒，沒有失敗或略過，JUnit 存於本機 `tmp/issue22-tests.xml`。該次執行期間完成最後的 Spec 修正，另以最終版本重跑本票 3 項公開介面測試，全部通過；mypy 套件與準備工具共 18 檔通過。未改動錄製器或部署遊戲插件。

測試穿過合成錄製、四檔封存、compiler、模型視圖與 TrainingIndex，驗證不足資料保持 pending、非法預測候選拒絕、修改協定 checksum 拒絕。原生 trial 產生器的輸出直接通過內容比對；保留組、重用 seed、改變 trial 用途／偏航後重新封存仍拒絕。揭露規則覆蓋有效的凍結順序，以及缺 checkpoint、提前凍結時間、使用 test／final 選模等拒絕案例。合成測試不算實機資料覆蓋或模型 gate 證據。

## Standards

獨立 agent 以 `ea035eb408680310381d83bd7e99efbb33201f6f` 為基準審查，硬性規範違反 0 項。兩項可直接修正的命名／重複邏輯已處理，複核無阻擋。另有一項低優先的跨層資料查詢觀察，目前只有單一工具消費者，依 Ponytail 不新增 wrapper，後續有第二個使用者再評估。

## Spec

獨立 agent 發現三項問題：baseline 狀態只明查 mouse、trial 產生器輸出尚須手動 seal、驗證器未直接綁定固定 trial artifact。已改為明查 mouse／wheel、產生器直接使用共用 seal 與原子發布，以及 required expected_id 對應凍結協定的 trials_id；不重新實作 System.Random。新增重新封存竄改偏航的拒絕測試，原 agent 複核未見剩餘問題。

Standards 無剩餘阻擋，Spec 三項均已解決；資料與人工 gate 仍待驗證。
