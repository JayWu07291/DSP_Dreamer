# Issue #31 修復後的正式訓練

使用者在首次[停止紀錄](issue-31-validation.md)後，要求修復 `actions.py`、`dataset.py` 及其他問題，完成後進行訓練。舊錯誤與用量仍保留，不覆寫首次停止證據。

## 已完成修復

新增[來源相容性紀錄](../protocols/source-compatibility-issue31.json)，只接受原 source-freeze ID 下兩組精確新舊指紋。互斥控制規則的 1,024 組測試與凍結版相同，runner metadata 仍由 compiler 保存。正式 loader 與輕量資料稽核使用同一核對器，其他改動仍拒絕。

來源檢查已移入既有預算 attempt，失敗自動記帳；checkpoint 的 implementation 清單包含相容性紀錄的 SHA-256。七份凍結 evaluation JSON、TrainingIndex、資料與 split 未變。

真實資料的輕量稽核已通過，報告位於本機 `runs/issue-31/resolved/data-audit.json`，相容性 artifact ID 為 `7bb58ba946fc69b3b4f7e8fb4475f74e2a578a1921fa571abece27e88656eef6`。這一步未重讀 RGB，正式執行仍須通過完整 loader。

## 本次執行配方

本機 `runs/issue-31/resolved/execute.py` 呼叫既有正式 loader、trainer、budget 與 evaluator，一次載入完整語料後依序執行：

1. 前置帳目執行八次更新的少量過擬合，固定兩個合法 train clips，保存同一 clip 在無 masking 評估下的訓練前後 loss。
2. A 帳目進行 64／96 tokens 各四次更新，使用相同 seed 2202、資料順序、完整 loss 與固定 200 圖。每組至多 1800 秒，判讀缺測保持待驗證，對照權重不當作正式候選。
3. 前置帳目以完整 loader/loss 量測 32／32／32／80-step 的四次更新，依當時 A 剩餘預算固定更新上限。
4. A 使用重新初始化的 64-token 模型，依共用控制器訓練、每 30 分鐘驗證存檔並執行完整重建評估。

微批次預設 2、累積 8。歷史預算、失敗用量與 2／4／16／6／4 小時上限沿用同一帳本。A 的完整人工 gate 通過後才可啟動 B；少量過擬合、短程對照或工程測試均不解鎖 B。

## 驗證與執行狀態

針對回歸三項通過，mypy 38 個檔案通過。完整 pytest 單輪 204 passed、0 failed／error／skip，675.89 秒，20 則既有警告。原始 log 與 JUnit 保存於 `runs/issue-31/resolved/pytest.log`、`pytest.xml`；修復檢查的指紋摘要見同目錄 `repair-checks.json`。

Standards／Spec 分別獨立審查，未見阻擋正式 A 執行的問題；Standards 唯一指出的測試命名已修正，兩軸均無剩餘問題。執行配方的計費、截止時間與 checkpoint 身分亦經獨立複核。實際更新與品質結果於執行後另行保存。
