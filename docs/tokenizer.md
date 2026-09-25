# Tokenizer 訓練與重建

Issue #24 接上既有 `TrainingIndex` 與 10 Hz 模型視圖，使用目前正式的 `action_catalog_v4`。不改寫凍結資料，不讀 offline-test 模型結果。工程驗證和重建品質 gate 分開。

## 安裝與執行

關閉 DSP，讓 RTX 5070 留出訓練空間。使用 repo 的 Python 3.12 環境：

```powershell
.venv/Scripts/python.exe -m pip install torch==2.9.0 torchvision==0.24.0 --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python.exe -m pip install lpips==0.1.4
.venv/Scripts/python.exe tools/train-tokenizer.py verify --output runs/issue-24/verification --updates 4
```

第一次執行會下載官方 AlexNet 權重至 `data/torch-cache`。LPIPS 固定 0.1.4、AlexNet、version 0.1、eval mode、spatial=false，完整 RGB 從 [0,1] 轉 [-1,1]，不縮放。配方保存 AlexNet 與 LPIPS 權重 SHA-256、PyTorch 與 torchvision 版本。

`verify` 完整核對來源 checksum 與覆蓋 gate，再對 64／96 tokens 各執行四次 optimizer updates，包含三次 32-step 和一次 80-step。第四次更新另從第三次 checkpoint 恢復，核對下一次 loss、資料順序及全部權重完全一致。這些探測有真實 loader、MSE + 0.2 LPIPS、BF16、activation checkpointing 和 AdamW 狀態。

兩個探測完成後，工具依較慢的實測速度固定共同對照步數，再分別重新初始化兩個模型。對照使用相同 seed 2202、資料順序、patch masks、loss、標註及 updates，各限 30 分鐘。正式 v1 保持 64 tokens。少量更新只能驗證管線，不能用來聲稱收斂或容量優劣。

預設 microbatch 2、accumulation 8。若顯存不足，保存失敗紀錄後只可加 `--microbatch 1`，改為 accumulation 16，以新輸出目錄重測；仍不足就停止，不縮圖或降低 loss。輸出目錄和 checkpoint 不覆寫。

`runs/tokenizer-budget.json` 累計第一階段 A 的探測、對照、訓練、恢復、評估與失敗重跑時間，合計限四小時。包含來源核對的整次命令時間，計法較 GPU 使用時間保守。中斷未正常收尾時，下次以中斷紀錄至當時的 wall time 補計，不把未記錄時間當成零。1/16 入口要求紀錄中已有 2/8 CUDA OOM。此紀錄供單一訓練程序使用，不應同時開啟多個訓練命令或刪除紀錄重置預算。

## 模型與恢復

原生 640×360 RGB 以 20×20 patches 形成 576 個位置。具有位置 embedding 的 patches 經 cross attention 讀入 64 個 learned latent queries，再經四層 width 512、8-head causal temporal attention，線性投影及 tanh 產生每步 64×32 表示。Decoder 從 latent cross attention 讀回各 patch，以 sigmoid 輸出 [0,1] RGB。

這沿用 #6 小型架構的空間壓縮方式。Decoder 每張圖只讀當步已包含歷史的 latent，因此可逐張解碼。它不是論文全部 transformer 結構的復現。每層 temporal attention 最多讀取當步及前 63 步。訓練時每張圖從 U(0,0.9) 取 masking 機率，以 learned embedding 替換 patches；推理不 masking。依據為 [Dreamer 4 §3.1](https://arxiv.org/html/2509.24527v1)。

AdamW 使用 betas 0.9/0.999、epsilon 1e-8、weight decay 0.01，bias 和 normalization 不衰減；global gradient clipping 1.0。前 5% updates warmup，之後 cosine decay 至 peak LR 1e-4 的 10%。LPIPS 逐圖 checkpoint，以降低 activation 記憶體需求；每張圖仍計入完整 loss。

```powershell
.venv/Scripts/python.exe tools/train-tokenizer.py train --updates 100 --max-seconds 14400 --output runs/tokenizer-v1
.venv/Scripts/python.exe tools/train-tokenizer.py train --checkpoint runs/tokenizer-v1/step-40.pt --output runs/tokenizer-resumed
```

步數只是指令示例，正式長程步數須先依完整路徑實測速度與研究預算固定。恢復沿用 checkpoint 配方，不重新解讀 `--updates` 或變更 schedule。每 30 分鐘保存 checkpoint，並用固定名單前八張 validation 圖檢查。階段候選另跑完整 200 圖。Checkpoint 包含配置、資料與凍結身分、metric 權重身分、模型、optimizer、schedule 所需總步數及目前步數、抽樣歷史、Python／NumPy／PyTorch／CUDA RNG；旁邊的 JSON 保存 checkpoint checksum。

## 重建評估與人工判讀

```powershell
.venv/Scripts/python.exe tools/train-tokenizer.py evaluate --checkpoint runs/tokenizer-v1/final-100.pt --output runs/reconstruction-v1
.venv/Scripts/python.exe tools/train-tokenizer.py score --metrics runs/reconstruction-v1/metrics.json --judgments runs/reconstruction-v1/judgments.json --output runs/reconstruction-v1/reviewed-gate.json
```

每張固定 validation 圖使用同回合、同合法區間內至多 64 步真實歷史，被測圖位於最後一步。輸出原圖及重建 PNG、逐圖 MSE／LPIPS／UI MSE、來源 capture、context 起點、checkpoint hash 與配方。MSE 使用量化前 float32 RGB；PNG 四捨五入為 uint8。UI 指標按每張圖事前標註矩形聯集取平均，再對有 UI 的圖等權平均。

複製 `judgments-template.json` 為 `judgments.json`，由人按凍結標註填入 `correct`、`reviewer`、`evidence`。判讀綁定 metrics、annotations 和 checkpoint 身分。游標、配方、物品／數字、連接的判讀規則沿用 [協定 v2](../protocols/evaluation-v2.md)。不從模型 loss 推定項目可辨識。

Gate 要求固定 200 張、17 個 task 各至少十張、四類關鍵項目及五種 UI 覆蓋。整體辨識至少 95%，每類至少 90%。未判讀仍留在分母，accuracy 為 null、狀態為 pending；缺類型或配額為 insufficient_evidence。工程驗證通過不啟動後續 dynamics 階段。

## 回歸檢查

```powershell
.venv/Scripts/python.exe -m pytest tests/test_tokenizer.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train-tokenizer.py
```

CPU 測試的 width 32 與兩步序列只供快速回歸。正式 CLI 固定 width 512，少量更新及恢復的正式證據必須由 `verify` 在真實資料與 GPU 上產生。PyTorch peak allocated／reserved 僅表示本行程，不是整卡取樣或閉迴路 VRAM 驗收。
