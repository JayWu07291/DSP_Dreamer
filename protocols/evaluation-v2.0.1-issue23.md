# Evaluation 2.0.1：Issue #23 本批工時驗收例外

2026-09-25，使用者在本對話明確回覆「同意工時例外」。本修訂依 [evaluation-v2](evaluation-v2.md) 的版本保存規則另立，僅調整 [Issue #23](https://github.com/JayWu07291/DSP_Dreamer/issues/23) 這批歷史示範的工時驗收。正式核准、適用 artifact IDs、來源 checksum 與修訂內容封印見 [evaluation-v2.0.1-issue23.json](evaluation-v2.0.1-issue23.json)。

## 適用範圍與決議

基礎協定為 evaluation-v2，版本 2.0.0，ID `40167e30d83bab5b60b19498ac45380899cd942d8f87fc347db37cae893a9e42`。本次是依附該協定的 2.0.1 範圍修訂，適用 TrainingIndex `7301b78d7d5caaa63b2f600201c9c41d0890123bfe47f1d264cc1e7aa3b2ba21` 與 data freeze `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f`。

原「資料與凍結順序」第 2 點要求約 3 小時初錄分析、其餘約 7 小時補錄，正常／恢復約 70／30 為人工工時。本批實際人工工時未紀錄，無法追溯；初錄、補錄、正常操作及恢復工時、工時比例均永久保留未知。使用者核准以驗收例外處理，不宣稱原工時安排已達標，也不以 capture、影片、完整回合、標註時數或預算代填。

本批以既有正式資料驗證與來源追溯、逐微任務 20／3／3 正例、固定 split 與保留試驗隔離、不可變凍結資料，以及六段人工確認的恢復示範完成交付。第八批診斷後沿固定順序補錄到第十八批的歷史證據保留。本次不要求額外錄製，沒有推定歷史工時預算已用盡。

後續新增示範須分別記錄正常操作、失誤恢復及排除的休息／等待時間。本例外不適用未來錄製，也不改容量不足就停止新增、不自刪 evidence、配額不足就保留缺口並停止依賴階段的要求。

## 版本與證據保存

本修訂以 `dsp-evaluation-protocol-amendment/1` 保存，與基礎 v2 一起解讀，只覆蓋上述本批工時驗收。它不是 `read_protocol` 的新輸入，也不替換既有評分協定身分。

v2 的 JSON／Markdown、TrainingIndex、資料凍結及六段人工確認的原 bytes、artifact IDs、split、所有無效判定均保留。舊報告與人工確認中的待決欄位代表當時狀態，由本修訂記錄後續核准；不得倒填舊檔。後續引用本批交付時應同時列基礎 protocol_id、data_freeze_id 與本修訂 artifact_id。

配額、抽樣、評分門檻、baseline、model action、recipe freeze、offline-test／final 隔離及揭露規則完全沿用 v2。本次修訂依據使用者核准的歷史缺測例外，沒有使用模型結果放寬門檻。

模型品質仍 `pending`，`training_authorized=false`，`offline_test_disclosure_authorized=false`。完成 #23 資料交付不代表模型 gate 通過；實際訓練、模型判讀及試驗須另依各自 gate 執行。

## 驗收依據

- [逐條核對及覆蓋統計](../docs/issue-23-status.md)。
- [資料凍結機器核對](../docs/issue-23-audit.json)，收尾重跑產生相同 artifact ID。
- [六段候選的原始來源](../docs/issue-23-recovery-review.json)與[使用者逐段確認](../docs/issue-23-recovery-confirmation.json)。
- [人工確認與驗收決議](../docs/issue-23-handoff.md)。
