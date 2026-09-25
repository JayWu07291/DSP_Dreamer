# 動作條件 dynamics

Issue #25 的工程入口包含凍結 tokenizer、動作條件訓練、checkpoint 恢復，以及固定 validation 序列的自由預測與配對評分，已完成修訂後的工程驗收。正式 A／B 訓練與實際模型品質驗收由 [#31](https://github.com/JayWu07291/DSP_Dreamer/issues/31) 執行；第一階段 B 尚未啟動，現有 tokenizer 重建 gate 仍為 `failed`。工程 fixtures 的預測評分與[結案結果](issue-25-closeout.json)標為 `engineering_only`，不能作為下一階段的合格模型。

## 模型與時間對齊

正式設定為 width 512、8 blocks、8 heads、8 register tokens，每個 block 做 spatial attention，第 4／8 個 block 再做 causal temporal attention，context 64 steps。影像表示沿用 64×32 tokenizer latents。原生 640×360 RGB 不縮放，任務條件及具特權狀態不送入 dynamics。

每個二元控制用獨立 off／on embedding，mouse 與 wheel 各有類別 embedding，相加後形成一個 action token；signal level 與 step size 用離散 embedding 組成另一個 token。採用 [ADR-0002](adr/0002-build-mode-control.md) 及修訂後 #25 的 `action_catalog_v4`／21 維，取代早期 v2／v3 敘述。載入任何權重前先驗完整 `ACTION_CODEC`，不接受舊寬度、控制順序或量化設定。

訓練從 `TrainingIndex` 的 train 合法視窗均勻抽樣。T 個 transitions 讀出 T+1 張觀測，latent `z_t` 配上進入該影格的 `a_(t-1)`；第一張的 action 為 no-op，只供歷史，不計 loss。Tokenizer 使用 eval 模式、關閉 masking 與梯度。Dynamics 使用三次 32-step、一次 80-step 更新；microbatch 2、accumulation 8，AdamW 與 LR schedule 沿用 #7。

Shortcut forcing 按 [Dreamer 4 第 3.2 節、式 6–8](https://arxiv.org/abs/2509.24527) 實作 x-prediction。最小 step 為 1/4，bootstrap step 為 1/2，以兩個不回傳梯度的 1/4 step 速度平均形成目標；flow 與 bootstrap loss 均乘 `0.9*tau+0.1`。本專題的兩項 loss 相加。Flow signal 從 0、0.1、0.25、0.5、0.75 均勻抽樣，bootstrap 從 0、0.25、0.5 抽樣，這是此實作的離散訓練配方。

自由預測每步固定四次 forward，`tau=0,0.25,0.5,0.75`。過去 context 按契約使用 signal level 0.1，即 `0.1*z + 0.9*noise`，四次 forward 共用該次 context noise。只在最初編碼真實歷史，後續使用模型生成的 latents；不餵入未來真圖。

## 指令

以下訓練命令必須等同一 tokenizer checkpoint 的重建 gate 通過才能執行。`100` 只是示例，正式 updates 需依完整 loader、loss、accumulation 的測速及剩餘預算固定。

```powershell
.venv/Scripts/python.exe tools/train-dynamics.py train --tokenizer runs/tokenizer-v1/final-100.pt --reconstruction-metrics runs/reconstruction-v1/metrics.json --reconstruction-gate runs/reconstruction-v1/reviewed-gate.json --updates 100 --output runs/dynamics-v1
.venv/Scripts/python.exe tools/train-dynamics.py train --checkpoint runs/dynamics-v1/step-40.pt --output runs/dynamics-resumed
.venv/Scripts/python.exe tools/train-dynamics.py evaluate --checkpoint runs/dynamics-v1/final-100.pt --output runs/prediction-v1
.venv/Scripts/python.exe tools/train-dynamics.py score --checkpoint runs/dynamics-v1/final-100.pt --metrics runs/prediction-v1/metrics.json --judgments runs/prediction-v1/judgments.json --output runs/prediction-v1/reviewed-gate.json
```

CLI 核對凍結 catalog、protocol、資料覆蓋、完整 checksum 與重建證據。它會重算重建評分，確認 report、人工判讀、checkpoint hash 及凍結身分完全相符，不能只提供一個 `passed` 字串。正式預測評分還須提供原 checkpoint 及 metrics 同目錄的 `recipe.json`，並核對記錄的實作 checksum；修改 `formal` 或重封 smoke metrics 不會使其通過。CUDA 訓練期間須關閉 DSP。

Checkpoint 保存 dynamics、AdamW、配方與排程進度、抽樣紀錄、Python／NumPy／PyTorch／CUDA RNG、資料身分及重建證據。凍結 tokenizer 以絕對路徑和 checksum 引用，恢復時必須保留上游 `.pt` 及旁邊的 `.pt.json`；不重複複製其權重。恢復沿用原配方，不能用 `--updates` 重新安排 LR。

每 30 分鐘保存 checkpoint，並對固定名單前四個序列做離線 validation。完整候選仍需另外跑全部 200 序列。`runs/dynamics-budget.json` 累計第一階段 B 的訓練、資料驗證、儲存、評估及失敗重跑，合計最多 16 小時。中斷未收尾會在下次保守補計 wall time。Windows 檔案鎖會拒絕同時使用預算的另一個程序，程序終止後系統釋放鎖；不可刪除紀錄重置預算。顯存不足的紀錄存在後才允許 `--microbatch 1`，改用 accumulation 16。

## 預測與判讀

沿用已凍結的 200 個 validation 序列，movement、ui、interaction、waiting 各 50。每個序列以 64 個歷史 transitions 的最後 next observation 起始，未來第 1／5／15 個 next observation 為評估目標。四個條件為正確動作、唯一 no-op、固定同 task／同類別 donor 的完整動作，以及複製最後歷史圖。前三個條件重設到同一 generation seed。

輸出包含原圖與各條件的 1／5／15 步 PNG、來源 capture、全圖 MSE／LPIPS、固定受影響區域的 LPIPS，以及配方與 checkpoint 身分。LPIPS 沿用 #24 的 AlexNet v0.1 與相同權重，不縮放裁出的區域。

將 `judgments-template.json` 複製為 `judgments.json`，依事前 key_states 判讀正確動作條件的第 15 步，填入 `correct`、`reviewer`、`evidence`。每個關鍵項目各佔一個分母；缺判保留分母、accuracy 為 null，狀態維持 pending。評分保存完整判讀內容，並列出各類與逐 task 結果。

第 5 步前三類各自對三個 baseline 比較。無動作差異或 baseline error=0 的配對列出排除理由；同一比較只用相同樣本計算兩邊平均，再計相對改善，至少 10%。分母為零或缺類別屬證據不足。第 15 步整體正確率至少 80%，前三類各至少 70%。等待另外報告。門檻與凍結資料保持原樣。

## 工程驗證

```powershell
.venv/Scripts/python.exe -m pytest tests/test_dynamics.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train-dynamics.py
```

測試穿過合成錄製、正式 compiler、模型視圖、tokenizer checkpoint、shortcut loss、恢復與預測 PNG／指標匯出，並檢查 action 因果性、恢復後下一次更新一致、tokenizer 權重不變，以及 gate 的配對分母與缺判處理。CPU 回歸使用 width 32／4 heads，其餘結構不變。另有 RTX 5070 正式寬度的合成 smoke，驗證 BF16、2/8 accumulation、32／80-step 更新、恢復與自由預測；見 [驗證紀錄](issue-25-validation.md)。合成資料測速不代表真實資料 throughput 或品質門檻。

目前重建 gate 未通過，正式 200 序列品質、真實資料 dynamics 訓練及第 15 步人工判讀均未執行。沒有產生合格第一階段 B checkpoint，也沒有揭露 offline-test 模型結果。
