# B 探索訓練

2026-09-28。依使用者要求，先用現有 tokenizer 嘗試 B。A 的 gate 仍為 pending，這次輸出是探索 checkpoint。

B 凍結 A 的 encoder 和 decoder，只更新 dynamics，學習由觀測歷史及低階鍵鼠動作預測後續 latent。它可以幫助判斷現有表徵能否支撐動態預測，但不會直接改善 A 的重構圖片。100 步只是初步觀察，不能據此判定 B 已收斂或模型架構無效。

## 配方

來源選 `runs/A-20260927-104240-538709/training/final-1000.pt`，累計 3431 次更新。它的完整 200 張重構 MSE／LPIPS 都略優於後來兩組 100 步版本。來源 SHA-256 為 `6cefc1379aa6bdb221b6c49b76c979a316df7f59b8f691182f94abe0efced4ee`。

| 項目 | 設定 |
| --- | --- |
| 配方檔 | [training_config_B_exploratory.py](../../training_config_B_exploratory.py) |
| 模型 | 既有 dynamics，寬度 1280、16 層、20 query heads／4 KV heads、64×32 latent |
| 初始權重 | dynamics 從 seed 新建；A 從上述 checkpoint 載入並凍結 |
| 更新目標 | 100 次完整 optimizer update，無訓練時間截止 |
| seed | 20260928 |
| LR | peak `1e-4`，10 步 warmup，cosine 至 `1e-5` |
| batch | 2 × 8，有效 batch 16 |
| 片段 | 32／80 transitions，三短一長；需 33／81 幀 |
| loss | running RMS 正規化 flow + bootstrap |
| 顯存 | 既有 `.75` allocator 上限、BF16、activation checkpointing |
| 資料 | 同一凍結 corpus，`verify_rgb=False`，略過全量 RGB 核對 |
| 檢查點 | 每 50 次更新或 1800 秒，先到者；另存 start、candidate 和 final |
| 預測評估 | 中途固定前 4 段，結束固定前 8 段；不是完整 200 段 gate |

本輪使用真實 B 的 encode、shortcut loss、梯度累積和 optimizer。測速跑四次更新後丟棄測速權重，再從同一 seed 新建正式實驗權重。用量記在探索帳本，測速不折抵 100 次完成目標。尚未取得真實 B 的測速結果，不能用 A 的每步秒數保證這輪耗時；測速完成後可從 log 的 `benchmark_update` 估計。

## 執行

關閉 DSP，在外部 PowerShell 執行：

```powershell
cd E:\GitHub\DSP_Dreamer
.venv/Scripts/python.exe -X utf8 tools/train.py B show-config --exploratory --config training_config_B_exploratory.py
.venv/Scripts/python.exe -X utf8 tools/train.py B run --exploratory --config training_config_B_exploratory.py --tokenizer runs/A-20260927-104240-538709/training/final-1000.pt --output runs/B-exploratory-3431-100
```

第一次執行不需要 `--restart`。若探索帳本已有舊實驗且確實要重新開始，才加 `--restart`，舊探索帳本會封存至此次 `.logs/previous-budget.json`。它不修改 A 的正式帳本或原有 checkpoint。

改步數和學習參數請編輯配方檔。若要調整結束時評估的段數，可加 `--prediction-limit N`，範圍 1–200，預設 8。執行中不要修改配置、來源 checkpoint 或訓練實作。

中斷後，用同一設定、`--exploratory` 和帳本最新完整 checkpoint 恢復到新的輸出目錄：

```powershell
.venv/Scripts/python.exe -X utf8 tools/train.py B train --exploratory --config training_config_B_exploratory.py --checkpoint <最新完整checkpoint> --output <未使用的恢復目錄>
```

恢復不加 `--restart`，不重新指定步數。若更改過 `--prediction-limit`，恢復也帶相同值。完成更新數以 checkpoint 的 step 計算，失敗時遺失的更新會重跑至原目標；嘗試次數和實際耗時另記，不會把故障當成完成更新。

若 CUDA OOM 需改 1／16，先用原 tokenizer、同一配置與 `--exploratory --microbatch 1` 執行 `B benchmark`，再用 `B train --checkpoint ... --microbatch 1` 恢復；原更新上限保持不變。探索與正式入口共用鎖，不能同時執行。

## 完成後看什麼

- `<output>.logs/events.jsonl`：每步總 loss、flow／bootstrap 原始值與 RMS、LR、梯度、抽樣和耗時。
- `<output>/training/run.json`：應為 `status=completed`、`updates=100`；`formal=false`、`quality_status=engineering_only` 是這輪預期狀態。
- `<output>/training/gate/prediction/metrics.json` 和 PNG：對同一段歷史比較正確動作、no-op、打亂動作、複製最後一張，在未來第 1／5／15 步的結果。
- `runs/B-exploratory-budget.json`：探索測速、訓練、失敗和恢復用量；正式 `runs/training-budget.json` 保留。

先看 loss 是否有限、flow 是否下降，再看正確動作相對 no-op／打亂動作的預測差異。複製最後一張是像素基線，含有真實原圖的清晰細節；A 的重構誤差會使這項比較對生成影像較嚴格，仍須照實呈現，不能把 tokenizer 的 UI 錯誤直接歸因於 dynamics。

目前固定前 8 段全部是 `movement`，只診斷移動預測，不是各類操作的均衡品質評估。這些結果只供決定是否繼續 B 或回頭改進 A，不會自動解鎖 second 或 third。完成後提供輸出目錄；不需要 Agent 持續監看訓練。

## 已完成的驗證

CPU 測試通過：訓練／配置／帳本／恢復的既有與新增測試共 21 項，另跑探索預測匯出與配置限制 2 項；後者包含一項重跑。`mypy` 的 38 個來源檔通過。探索測試涵蓋 tokenizer 凍結、精確恢復、超過時間仍完成更新目標、共用鎖、來源模型指紋，以及拒絕把探索 checkpoint 宣告為正式來源。

另用上述真實 A checkpoint 與凍結資料，在 CPU 建立完整的 275,689,120 參數 dynamics，確認來源身分、可用訓練片段和 tokenizer 凍結。過程沒有 optimizer update、沒有使用 GPU，也未改動正式帳本。這只驗證載入與連接；實際 GPU 顯存及每步耗時仍由使用者執行時的 benchmark 確認。紀錄在 `runs/issue-31/B-exploratory-checks/`。
