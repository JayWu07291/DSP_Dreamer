# 批次試驗、選模與統計

Issue #30 的工程入口為 `python -m dsp_dreamer.evaluation_batch`，Python 入口為 `run_batch(plan, output, execute, ffmpeg=...)`。執行器產生錄製證據，批次入口依序呼叫四檔驗證、正式 compiler、dataset loader 與 #29 的 `episode_result`，再統計結果。執行器不能自行提交成功數或評分。

目前只接受 `engineering_only=true` 的計畫、合成錄製與明確標記的模擬候選資格。這沿用 #29 尚未開放正式 checkpoint 的限制。工程報告固定 `qualified=false`、`formal_valid_episodes=0`，不能拿來挑選正式模型。#35 必須先接妥 #32／#33 的適用離線 gate、#34 的實機資源／延遲證據及正式 runner 身分，才可開放正式批次。既有 40 份正式 manifests 與目前輸入設定 hash 的差異也仍須處理。

## 執行契約

計畫使用內容封印的 `dsp-evaluation-batch-plan/1`，包含 `engineering_only`、`trials`、`registry`、`candidates`。`trials` 沿用 `dsp-evaluation-trials/1`，固定 10 development／30 final；`registry` 沿用 split registry。每個候選含 `stage=2/3`、`checkpoint` 絕對路徑、`file` checksum／bytes，以及 `fixture_eligible`。這個欄位只模擬資格，不能表示真實 gate 已通過。計畫可用既有 `evaluation_protocol.seal` 封印。

工程 manifests 不得與正式保留試驗共用 manifest ID、split group、偏航或任何 RNG seed。若提供訓練索引，還會核對來源 manifests，拒絕共用 split group、偏航與 seeds。錄製另須 `diagnostic_mode=true`，因此不提供合法訓練 transitions。每次執行前後核對 checkpoint checksum；每次返回的完整 manifest 必須與要求相同。

`execute(request, attempt_dir)` 每次收到獨立輸出目錄與完整要求。它應發布錄製四檔，返回 `{"evidence": "錄製證據絕對路徑"}`，可附 `failure_labels`。`request` 包含原計畫 ID、候選、purpose、完整 trial manifest 及從 0 起算的 retry。呼叫端不得改寫既有結果；批次輸出目錄必須尚不存在。

命令列以 `--execute` 指定單回合執行器，後面所有參數交給該命令。批次會再附加兩個絕對路徑，依序為 `request.json` 與應寫入的 `executor-response.json`。標準輸出和錯誤保存為 `executor.log`。範例中的 `executor.py` 由呼叫端提供，並遵守上述錄製證據契約。

```powershell
.venv/Scripts/python.exe -m dsp_dreamer.evaluation_batch --plan fixture-plan.json --out runs/batch-new --ffmpeg E:/SubtitleEdit-Windows-x64/SpeechToText/Purfview-Faster-Whisper-XXL/ffmpeg.exe --execute .venv/Scripts/python.exe executor.py
```

兩個合格模擬候選各跑同一份 10 development manifests，依完整成功、電磁矩陣科技、基礎製造、基礎物流、自動化冶金、電磁學、登陸艙拆完的到達數逐項比較。全同保留第二階段，時間不參與。單一候選直接進 final，不補第二個候選；沒有候選則輸出 `no_qualified_candidate`，不呼叫執行器。選擇結果先封存為 `selection.json`，才讀取 final 結果。

Final 逐份完成 30 個有效回合。無效或不完整回合以原 manifest 重試，每次都保留 request、response、錄製、dataset 與 result。連續三次無效立即停止整個批次，不能改用另一個候選或另一份 manifest；有效回合會清零連續無效計數。執行器錯誤、契約拒收與使用者中斷也留存原因。中斷輸出 `interrupted`，不自動繼續；程序被作業系統強制終止時，已寫出的各次產物仍保留，本版不提供自動恢復。

## 報表與時間

`report.json` 保留所有嘗試、原始計數、無效比例、重跑次數、原因、候選與來源 checksum、完整逐步控制結果及 development／final 統計。`nodes.csv` 匯出節點計數、分母、Wilson 區間、active 完成分母與時間。報告保存評分器 checksum、協定 ID、計畫 ID 及校準 ID，凍結的 v2 協定檔案保持原 bytes。

16 個微任務與七個背景里程碑的累計到達率分母都是該候選、該 purpose 的全部有效回合。微任務另列啟用後完成數／啟用回合數；非 active 完成可以計入累計到達，未啟用不列為 active 失敗。完整成功與到達率均附 Wilson 95% CI，z=1.959963984540054。零分母的 rate／CI 為 null；零成功保留 0/N。

時間沿用 compiler 的觀測邊界：節點首次出現在 `node_completions` 時，以該 transition 的 next observation request ticks 確認到達；微任務從首次 active 觀測起算，背景從回合起點起算。這是 20 Hz 錄製的確認時間，不是影片播放時間，也不是推測事件發生在兩張畫面之間的精確時間。最後觀測可以在終止事件之後，因此報告仍保留原始 ticks。到達者報 median、Q1、Q3 與 IQR，分位數採線性插值；未到達數與非 active 完成而沒有啟用起點的數量另列，不補零秒。

`failure_labels` 可同時含 `observation_reconstruction`、`injection`、`wrong_action`、`task_reward`、`stagnation`、`unknown`。每筆人工分類需提供存在於該錄製的 `capture_ids` 或 `event_refs`，例如 `{"label":"wrong_action","capture_ids":[0],"event_refs":[]}`。沒有人工分類的失敗預設 `unknown`、`classification_status=pending`，不猜模型內因。

停滯校準只讀 v4 的 train 示範，按不同有效回合收集完整合法的 active 啟用至完成時長。每個 task 至少 20 個回合才計算 `2 × p95`；不足時 threshold 為 null、狀態為 `insufficient_evidence`。CLI 可同時提供 `--training-index` 與 `--training-source`。工程批次只使用合成訓練來源校準，實機資料的校準可透過 `calibrate_stagnation(index)` 產生，兩者保留各自身分。停滯只追加診斷標籤，從不提早終止回合。

## 驗證

```powershell
.venv/Scripts/python.exe -m pytest tests/test_evaluation_batch.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer
```

測試直接建立合成錄製、無損封存並經批次入口編譯，不 mock #29 的評分。涵蓋單／雙／無候選、全成功、零成功、未啟用、非 active 完成、相同 manifest 重試、三次無效停止、每一級選模優先序、速度平手、19／20 回合停滯校準、訓練 split、證據引用、CLI 執行失敗與正式 manifests 拒收。這些案例均不算正式 development／final 試驗。
