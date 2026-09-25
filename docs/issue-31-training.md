# Issue #31 修復後的正式訓練

使用者在首次[停止紀錄](issue-31-validation.md)後，要求修復 `actions.py`、`dataset.py` 及其他問題，完成後進行訓練。舊錯誤與用量仍保留，不覆寫首次停止證據。

最新結果：重設預算後，A 已完成全部 756 次更新與固定 200 圖評估。但抽查重建仍呈現雜訊狀紋理，無法辨識場景與關鍵 UI，不能視為模型品質合格。正式人工 gate 尚有 15 項待判讀，B 未啟動。完整機器可讀證據見 [issue-31-training-results.json](issue-31-training-results.json)。

## 已完成修復

新增[來源相容性紀錄](../protocols/source-compatibility-issue31.json)，只接受原 source-freeze ID 下兩組精確新舊指紋。互斥控制規則的 1,024 組測試與凍結版相同，runner metadata 仍由 compiler 保存。正式 loader 與輕量資料稽核使用同一核對器，其他改動仍拒絕。

來源檢查已移入既有預算 attempt，失敗自動記帳；checkpoint 的 implementation 清單包含相容性紀錄的 SHA-256。七份凍結 evaluation JSON、TrainingIndex、資料與 split 未變。

真實資料的輕量稽核已通過，報告位於本機 `runs/issue-31/resolved/data-audit.json`，相容性 artifact ID 為 `7bb58ba946fc69b3b4f7e8fb4475f74e2a578a1921fa571abece27e88656eef6`。這一步未重讀 RGB；後續兩次正式執行均另行通過完整 loader。

## 本次執行配方

本機 `runs/issue-31/resolved/execute.py` 呼叫既有正式 loader、trainer、budget 與 evaluator，一次載入完整語料後依序執行：

1. 前置帳目執行八次更新的少量過擬合，固定兩個合法 train clips，保存同一 clip 在無 masking 評估下的訓練前後 loss。
2. A 帳目進行 64／96 tokens 各四次更新，使用相同 seed 2202、資料順序、完整 loss 與固定 200 圖。每組至多 1800 秒，判讀缺測保持待驗證，對照權重不當作正式候選。
3. 前置帳目以完整 loader/loss 量測 32／32／32／80-step 的四次更新，依當時 A 剩餘預算固定更新上限。
4. A 使用重新初始化的 64-token 模型，依共用控制器訓練、每 30 分鐘驗證存檔並執行完整重建評估。

微批次預設 2、累積 8。這份原始配方沿用歷史預算與失敗用量；後續使用者授權重設另見下文。A 的完整人工 gate 通過後才可啟動 B；少量過擬合、短程對照或工程測試均不解鎖 B。

## 驗證與執行狀態

針對回歸三項通過，mypy 38 個檔案通過。完整 pytest 單輪 204 passed、0 failed／error／skip，675.89 秒，20 則既有警告。原始 log 與 JUnit 保存於 `runs/issue-31/resolved/pytest.log`、`pytest.xml`；修復檢查的指紋摘要見同目錄 `repair-checks.json`。

Standards／Spec 分別獨立審查，未見阻擋正式 A 執行的問題；修復程式的測試命名已修正，兩軸均無剩餘問題。執行配方的計費、截止時間與 checkpoint 身分亦經獨立複核。重設腳本有一項非阻擋建議：改寫帳本前先核對歷史匯入來源；本次重設已成功完成並保存 receipt，未觸發該中途失敗情境。實際更新與品質結果已保存於上述機器可讀報告。

## 已完成的前置與對照

2026-09-25 18:07（Asia/Taipei）啟動。本次完整 loader 用時 1653.86 秒，通過 24 份真實資料集的影像與凍結索引核對；index ID 仍為 `7301b78d7d5caaa63b2f600201c9c41d0890123bfe47f1d264cc1e7aa3b2ba21`。

八次少量過擬合更新後，同一個固定 32-step clip、無 masking 的完整 loss 從 0.422978 降至 0.320290（MSE 0.186192 → 0.172325，LPIPS 1.183928 → 0.739827）。原始樣本、訓練歷史與評估值保存在 `runs/issue-31/resolved/overfit.json`。

兩組對照各四次更新，實際 samples 完全相同，且各完成固定 200 圖的重建評估：

| Tokens | 更新用時（秒） | 峰值 allocated（GiB） | 峰值 reserved（GiB） | MSE | UI MSE | LPIPS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 65.578 | 2.402 | 3.730 | 0.079140 | 0.120983 | 0.922425 |
| 96 | 55.968 | 2.469 | 3.801 | 0.079026 | 0.119646 | 0.958881 |

更新用時不含 checkpoint 與評估；兩者均另計入同一 A 預算。短程計時未重複量測，不據此宣稱 96 tokens 更快。兩組各有 15 個關鍵項目尚待人工判讀，accuracy 為 null，gate 為 pending。這些對照不解鎖 B，也不改變正式 v1 的 64-token 配置。

原始對照報告為 `runs/issue-31/resolved/comparison-64.json`、`comparison-96.json`；同目錄的 `reconstruction-64/`、`reconstruction-96/` 保存 PNG、metrics、recipe 與人工判讀模板。

## 正式 A 首次執行與恢復

獨立測速的 32／32／32／80-step 更新分別為 12.656、12.390、12.797、28.078 秒。控制器依 A 當時剩餘 11692.736 秒與既定 90% 更新比例，固定上限為 638 次；不得因訓練速度改變而追加。計畫保存在 `runs/issue-31/resolved/A-plan.json`。

正式 A 於 18:44 啟動，使用重新初始化的 64-token 模型、微批次 2、累積 8。19:09 在第 87 次更新前保存預算帳本時，`os.replace` 發生 `PermissionError: [WinError 5]`；已完成 86 次更新、扣除 87 次更新額度，該 attempt 計費 1491.312 秒。當時尚未到下一次 30 分鐘存檔，最新完整 checkpoint 為 `A/validation-0-0.pt`（step 0）；未保存的 86 次更新不能當作可恢復成果。

隔離重現顯示，Windows 上開啟中的讀取 handle 會阻擋目的檔案的原子替換；關閉 reader 後替換成功。本次外部監看正在讀取可變帳本，與錯誤時間重合，因此停止這種監看方式。失敗原始紀錄與帳本快照保存在 `runs/issue-31/resolved/storage-failure.json`、`budget-after-failure.json` 和 `A/run.json`。

監看方式改為使用程序內記憶體取得進度，每 30 秒追加到 `progress.ndjson`；外部只讀這份進度檔，執行期間不開啟可變帳本。

## 使用者授權重設

使用者在此次失敗後明確要求：「請重設預算，我不希望因為這個類別的問題導致模型少訓練次數」。因此本次改用全新預算 ID、更新計畫與模型，重新提供前置／A／B／第二／第三階段的 2／4／16／6／4 小時額度。這是使用者對原累計預算規則的明確變更，不宣稱新舊執行合計仍符合原先單一 32 小時帳目。

`runs/issue-31/restarted/reset-budget.py` 將舊帳本完整封存為同目錄的 `previous-budget.json`，並保存含授權原文及指紋的 `reset.json`。新帳本保留已匯入來源的識別，以免既有 CLI 再次扣除已封存的舊用量；已完成的過擬合和對照證據繼續保留。

新執行配方 `runs/issue-31/restarted/execute.py` 重新通過完整 loader、以完整 4 小時 A 額度測速決定新更新上限，再從零開始正式 A。產品 `.py`、資料凍結、loss、seed、64-token 與 2/8 配置維持不變。執行配方和預算重設各有指紋紀錄。

## 重設後的正式結果

新帳本 ID 為 `991a8127-d941-4de9-a8ca-35cbe5f30b04`。19:17 啟動完整 loader，19:48 啟動 A，23:27 完成（同日，Asia/Taipei）。重新測速的四次更新為 14.718、13.016、12.015、28.797 秒，據此固定 756 次更新。本次完整執行無 OOM、非有限 loss 或帳本存取錯誤。

| 帳目 | 本次用量（秒） | 剩餘（秒） | 狀態 |
| --- | ---: | ---: | --- |
| 前置 | 1841.610 | 5358.390 | 完整 loader 與測速完成 |
| A | 13154.766 | 1245.234 | 756／756 更新與完整評估完成 |
| B | 0 | 57600 | 等待 A 人工 gate |
| 第二階段 | 0 | 21600 | 未啟動 |
| 第三階段 | 0 | 14400 | 未啟動 |

A 用時 3 小時 39 分 14.766 秒，包含初始化、七次定期驗證、checkpoint 及最後 200 圖評估。最後一次訓練 loss 為 0.137381，最後 20 次平均為 0.139685；訓練 loss 不能替代辨識品質門檻。

| 驗證 checkpoint 更新數 | 評估圖數 | MSE | LPIPS |
| --- | ---: | ---: | ---: |
| 111 | 8 | 0.056477 | 0.499019 |
| 219 | 8 | 0.057118 | 0.495224 |
| 318 | 8 | 0.056735 | 0.487586 |
| 424 | 8 | 0.057237 | 0.486244 |
| 530 | 8 | 0.058329 | 0.487038 |
| 636 | 8 | 0.058290 | 0.486589 |
| 740 | 8 | 0.056500 | 0.486454 |
| 756（完整 gate） | 200 | 0.052686 | 0.448674 |

完整評估 UI MSE 為 0.082176。200 張原圖與 200 張重建 PNG 的指紋已逐一核對，gate 經 CPU 重算一致，七份 evaluation 凍結檔案與 checkpoint 實作指紋均通過核對。最後 checkpoint 包含模型、optimizer、RNG 與訓練控制狀態。

以下均為本機產物，位於 `runs/issue-31/restarted/`：

- `A/final-756.pt`：最新完整恢復點，保留相鄰 `.pt.json`。
- `A/candidate-756.pt`：200 圖完整 gate 實際評估對象；SHA-256 為 `c8c0cf72df2ee4d00be95e4acf7ecfa2beae419014e6e346ad4151cd93159c83`。人工 score 使用此檔，不使用 final 檔案的 hash。
- `A/gate/`：原圖、重建圖、metrics、recipe、gate 與未填寫的 `judgments-template.json`。
- `human-review.md`：7 組圖對照及 15 個關鍵項目的區域、預期內容，供人工判讀。
- `budget-completed.json`：執行完成時的不可覆寫帳本快照。

## 品質結論與停止點

Codex 抽查 R031、R111 的重建圖，兩者皆呈現近似的雜訊狀紋理，未保留可辨識的場景與 UI。這是模型輸出品質不足的直接觀察，不能因 loss 降低或訓練程序完成就宣告 A 合格；目前也沒有證據能確定模型未學會重建的根因。

正式辨識 accuracy 仍為 null：游標 2 項、配方 1 項、物品數字 10 項、連接關係 2 項，共 15 項皆未填入人工結果。總體 ≥95%、每類 ≥90% 的門檻維持不變。`quality_status=pending`、`qualified=false`，沒有啟動 B、第二或第三階段，沒有把抽查觀察冒充人工判讀。

下一步應先完成這份候選的人工判讀並診斷重建品質問題；目前 checkpoint 不應當作合格 tokenizer 交給 dynamics 訓練。
