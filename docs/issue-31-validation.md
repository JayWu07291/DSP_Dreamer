# Issue #31 第一階段執行停止紀錄

2026-09-25，依 [#31](https://github.com/JayWu07291/DSP_Dreamer/issues/31) 的資料錯誤停止規則，正式入口在凍結實作檢查時拒絕執行。此次沒有完成測速更新，沒有開始 A 或 B，也沒有新的模型品質結果。交付的是可追溯的停止結論，不是模型訓練完成或收斂失敗。

完整欄位、原始錯誤、歷史對照、預算與檔案指紋見 [機器證據](issue-31-results.json)。受測提交為 `43c8ef19292ecef2173899a71ac6ad608ce017db`。本次只新增驗收文件，沒有改動模型、loader、凍結資料、split 或品質門檻。

## 停止位置與原因

在 DSP 已關閉、BF16 CUDA 可用時執行：

```powershell
.venv/Scripts/python.exe -u -X utf8 tools/train.py A benchmark --output runs/issue-31/A-plan.json
```

命令以 exit code 1 結束。`read_frozen_evaluation` 在建立訓練帳本及載入完整語料前拋出：

```text
Frozen implementation changed: dsp_dreamer/actions.py
```

逐檔核對找到兩項差異，並非單純換行格式：

| 檔案 | 凍結／目前 bytes | 差異來源 |
| --- | ---: | --- |
| `dsp_dreamer/actions.py` | 2874／2885 | `08cfa39`，#27 抽出 `EXCLUSIVE_CONTROLS` 並改寫互斥組合檢查。 |
| `dsp_dreamer/dataset.py` | 24557／24634 | `6f45531`，#29 編譯時增加保留 manifest 的 runner metadata。 |

另五個實作檔案與凍結 checksum 相同。七個 evaluation JSON 的 bytes、SHA-256 和封印仍相同，TrainingIndex 封印及其已保存的 coverage gate 也通過核對。這些檢查沒有重讀 RGB、重算合法起點或 active reward，不能替代完整 loader 驗證，也不能據此宣稱資料已損毀。

既有 `tools/verify-data-freeze.py` 同樣在 `actions.py` 拒絕，未產生通過報告。原始日誌位於本機 `runs/issue-31/A-benchmark.log`、`runs/issue-31/data-audit.log`；日誌指紋及診斷全文已保存於機器證據。未產生 `A-plan.json`，沒有可供正式訓練使用的更新上限。

恢復執行前，須先解決目前 loader 實作與來源凍結版本的相容性，再通過原有身分與完整內容驗證。此次未改寫凍結 checksum、撤回 #27／#29 功能或降低檢查條件。前置 tickets 已關閉，仍不代表目前版本可通過此項檢查。

## 驗收狀態

| #31 要求 | 本次狀態與實際分母 |
| --- | --- |
| 正式資料、完整 loader/loss 測速及少量過擬合 | 啟動檢查未通過。測速完成 0 updates；完整路徑 throughput、更新上限、過擬合結果均未取得。 |
| 相同 updates、資料順序、seed、loss 的 64／96 對照，各最多 30 分鐘 | 本次未執行。另核對 #24 的既有四步對照，僅列歷史證據，不作本次正式結果。v1 維持 64。 |
| A 可恢復 checkpoint、固定 200 圖與整體 95%／每類 90% gate | A 未執行，新增 checkpoint 0、評估圖數 0。辨識率與分母為未知，不能寫成 0% 或 0／200。既有 #24 品質未通過，見下表。 |
| A 通過後凍結 tokenizer，B 評估 200 序列、1／5／15 步與全部配對 baseline | B 未執行，評估序列 0，配對指標、checkpoint 銜接及凍結證據均未產生。沒有合格 A 候選。 |
| 每 30 分鐘驗證存檔、停止及預算限制 | 啟動檢查即停，新增定期驗證／checkpoint 0；沒有到達 30 分鐘排程。未重試正式 GPU 工作，未追加預算。 |
| 原始指標、分母、版本與狀態 | 已保存本次錯誤、指紋、預算及未執行欄位。歷史通過的資料覆蓋、未通過的四步品質與本次未執行的模型評估分開記錄。 |

這個停止結論不解鎖 #32、#33 或任何要求合格模型的工作。沒有揭露 offline-test 模型結果，也沒有進行 development／final 試驗。

## 資源與累計預算

實機為 RTX 5070，回報顯存 12,227 MiB、driver 610.62；CPU 為 i5-13500，系統回報 RAM 34,121,097,216 bytes。PyTorch `2.9.0+cu128` 的 CUDA 與 BF16 可用。啟動前整卡用量 1,939 MiB，後續快照為 1,994 MiB；這是靜態讀值，沒有訓練峰值或連續取樣，不能當成正式 throughput 或閉迴路資源驗收。

| 帳目 | 上限秒數 | 已用秒數 | 剩餘秒數 |
| --- | ---: | ---: | ---: |
| preflight | 7200 | 122.4030558 | 7077.5969442 |
| A | 14400 | 2305.2320443573 | 12094.7679556427 |
| B | 57600 | 0 | 57600 |
| second | 21600 | 0 | 21600 |
| third | 14400 | 0 | 14400 |
| 合計 | 115200 | 2427.6351001573 | 112772.3648998427 |

A 保留 #24 既有 2305.2320443573 秒；preflight 保留 #25 兩次 smoke 共 120.031 秒。本次失敗命令的工具計時為 2.3720558 秒，包含 shell／Python 啟動，保守全額計入 preflight，沒有把它稱為 GPU 計算時間。

現有 CLI 在建立帳本前就核對來源，因此這次失敗沒有自動記帳。已將工具回傳的耗時與失敗日誌保存至 `runs/issue-31/startup-failure.json`，再透過既有 `TrainingBudget.import_history` 匯入唯一的 `runs/training-budget.json`。沒有改動 `runs/tokenizer-budget.json` 或重置額度。封印後快照在 `runs/issue-31/budget-snapshot.json`，機器證據亦保存完整副本。人工判讀與 CPU 工程回歸另計。

## 保留的 #24 四步對照

兩組使用相同正式資料、seed 2202、四次更新、逐次資料順序、完整 loss、masking 規則及標註。每組上限 1800 秒，序列長度為 32／32／32／80。本次核對既有 run、checkpoint 及 sidecar 指紋，並以原人工判讀重算 gate，結果相同。沒有重新訓練或重生圖片。

| 歷史候選 | 更新秒數 | MSE | LPIPS | UI MSE | 辨識正確／總數 | Gate |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 64 tokens，4 updates | 64.188 | 0.079139906 | 0.922425270 | 0.120983143 | 0／15 | 未通過 |
| 96 tokens，4 updates | 58.844 | 0.079025909 | 0.958880935 | 0.119646446 | 0／15 | 未通過 |

每組原評估為固定 200 圖，17 個 task 各至少十圖；每組人工判讀 15／15，缺判與排除均為 0。兩組各類皆為游標 0／2、配方 0／1、物品與數字 0／10、連接 0／2。UI 指標來自五張圖、568,351 個聯集 pixels。完整數值與逐次 loss／抽樣見機器證據，判讀原文見 [#24 人工紀錄](issue-24-human-review.json)。

這些四步結果不支持長程收斂或 64／96 容量優劣，也不能取代本次未完成的前置過擬合與正式 A／B 工作。舊 checkpoint 缺少現行統一控制狀態，未登錄為本次可恢復點或合格候選。

## 檢查

七份凍結 JSON、五份相符實作及兩份不符實作已逐項核對；兩個歷史 checkpoint、sidecar、配方、逐次抽樣與重建評分結果核對通過。Mypy 檢查 36 個檔案通過，完整 pytest 單輪 201 passed、0 failed／error／skip，耗時 714.24 秒，20 則警告。原始日誌與 JUnit 位於 `runs/issue-31/checks/`，指紋已收入機器證據。`git diff --check` 通過。

```powershell
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train.py tools/train-tokenizer.py tools/train-dynamics.py tools/train-agent.py
.venv/Scripts/python.exe -X utf8 -m pytest -q --basetemp=runs/issue-31/checks/pytest --junitxml=runs/issue-31/checks/pytest.xml
```

這些是 CPU 工程回歸結果，不取代失敗的正式來源檢查或尚未執行的模型品質 gate。重跑回歸時使用新的 `--basetemp` 與 JUnit 輸出位置，保留本次證據。

## Standards

以 `43c8ef19292ecef2173899a71ac6ad608ce017db` 為基準獨立審查兩份新增文件，未發現專案規範、領域用語或證據格式違反。未解決 finding 0 項。

## Spec

獨立審查確認 #31 的資料錯誤停止規則適用於此次凍結實作指紋不符。A、B、正式對照及品質 gate 均如實標為未執行；歷史結果、失敗用量與下游資格分開記錄。未發現漏項、範圍擴張或錯報完成，未解決 finding 0 項。
