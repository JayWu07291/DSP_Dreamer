# 固定任務想像訓練與候選匯出

Issue [#27](https://github.com/JayWu07291/DSP_Dreamer/issues/27) 交付第三階段工程路徑。正式訓練與候選品質由 #33 驗收；目前第二階段尚無合格正式 checkpoint，因此本次只執行合成資料測試。

## 權重與 rollout

`ImaginationTrainer` 載入第二階段全部 dynamics 與 agent 權重。Tokenizer、dynamics、task embedding、query、cross-attention、normalization 與 reward head 都凍結；複製第二階段 policy heads 作為凍結 prior。只有 binary／mouse／wheel policy heads 與新增的 value head 可更新。更新前後及存檔前核對四組凍結權重的 SHA-256；讀取 checkpoint 時另與第二階段來源核對。

每個 update 從合法 train sequences 均勻抽樣，每個 context 只產生一條 rollout。三次 32-step 後一次 80-step，microbatch 2／accumulation 8，或 1／16。Tokenizer 編碼完整 context 後保留最後 64 steps；每條 rollout 的 task 固定為 context 最後一個觀測的 active task，歷史不因提示切換而重設。生成 15 個動作與後續 latents，另外保留第 16 個 state 的 value 作 bootstrap。Dynamics 沿用四次 shortcut forward 與 signal=0.1。

沿用 action_catalog_v4、21 個 binary controls、121 mouse 與 3 wheel。互斥控制群組直接從「全關或只有一個開啟」的條件分布抽樣，其餘按鍵仍是 Bernoulli。分組來自 codec 的同一份互斥規則；PMPO log-probability 與 KL 使用同一個正規化分布，不把修正前的機率套在修正後動作上。離線 policy 評分仍使用第二階段原有的原始 threshold／argmax 與禁止組合率。

## Loss 與預算

Reward 由凍結 head 的距離 0 預測提供；等待 task 的 reward 固定為零。Value 使用既有 255 bins symexp twohot，在原 reward 單位插值。Return 為 `r_t + 0.997 * ((1 - 0.95) * v_(t+1) + 0.95 * R_(t+1))`，末端 bootstrap 為 `v_15`，所有 target 都停止梯度。

PMPO 將整個 effective batch × 15 steps 依 advantage 正負分組，正組含零。兩組各自平均 log-probability，權重各 0.5，空組貢獻零；另加 0.3 × KL(policy‖prior)。Value loss 為 twohot cross-entropy。公式依據為 [Dreamer 4 §3.3，式 10–11](https://arxiv.org/html/2509.24527v1#S3.SS3)。

現有模型沒有 imagined terminal／continuation head，因此固定 horizon 內視為持續，末端用 value bootstrap；不把真實後續 task 切換或終止標籤套到生成軌跡。這是目前固定長度工程模型的限制，不能據此判定遊戲完成或失敗。

Policy／value peak LR 分別為 3e-5／1e-4，沿用 AdamW、5% warmup、cosine 至 10%、weight decay 0.01 及 gradient clipping 1.0。先分 microbatch 生成無梯度 rollout，再一次計算小型 heads 的整批 loss，避免各 microbatch 的正負例比例改變 PMPO 權重。最長四小時；deadline 在 rollout 和 optimizer update 前檢查。每 30 分鐘保存 checkpoint 並跑固定前四個 validation 預測序列。跨程序、失敗重跑與評估的統一預算管理仍由 #28 承接。

## 正式命令

以下路徑只示範檔案關係；updates 必須由完整 loader／loss 測速決定。第二階段需已有同源、完整且 passed 的 reward／policy／dynamics gate。CLI 不提供跳過 gate 的選項。

```powershell
.venv/Scripts/python.exe tools/train-agent.py imagine --stage-two runs/agent-v1/final-100.pt --metrics runs/agent-metrics/metrics.json --agent-gate runs/agent-gate.json --prediction-dir runs/agent-prediction --prediction-gate runs/agent-prediction/reviewed-gate.json --updates 100 --output runs/imagination-v1
.venv/Scripts/python.exe tools/train-agent.py imagine --checkpoint runs/imagination-v1/step-40.pt --output runs/imagination-resumed
.venv/Scripts/python.exe tools/train-agent.py evaluate --checkpoint runs/imagination-v1/final-100.pt --output runs/imagination-metrics
.venv/Scripts/python.exe tools/train-agent.py predict --checkpoint runs/imagination-v1/final-100.pt --output runs/imagination-prediction
.venv/Scripts/python.exe tools/train-agent.py score-prediction --checkpoint runs/imagination-v1/final-100.pt --metrics runs/imagination-prediction/metrics.json --judgments runs/imagination-prediction/judgments.json --output runs/imagination-prediction/reviewed-gate.json
.venv/Scripts/python.exe tools/train-agent.py export --checkpoint runs/imagination-v1/final-100.pt --metrics runs/imagination-metrics/metrics.json --prediction-dir runs/imagination-prediction --prediction-gate runs/imagination-prediction/reviewed-gate.json --output runs/imagination-candidate
```

評估與第二階段共用 `evaluate`、`predict`、`score-prediction`、`score`，包含相同 validation 分母、train baseline、人工判讀及門檻。匯出會重新核對三項 gate 與來源第二階段資格，不採信外加的 passed 字串。只有正式 checkpoint 且三項都 passed 才有 `qualified=true`，可交給 development。Pending、failed、證據不足及工程候選可保留診斷，但不取得 development 資格。

匯出目錄包含 `model.pt`、checksum sidecar 與 `candidate.json`。Manifest 保存完整 codec／catalog、資料 index 和 sources、模型及訓練配方、第二階段與 tokenizer 來源、實作 checksum、工具版本、凍結權重 hash 及評分證據。Checkpoint 另含 optimizer、value、prior、RNG、更新數與耗時，恢復後延續訓練。上游 checkpoint 與凍結資料仍須保留在其來源位置；這不是移機即用的獨立封裝。

所有 checkpoint 先核對完整 codec 再載入權重；17、18、20 維或錯順序、錯量化設定都不能冒用 v4。Stage-two restore 不接受第三階段 checkpoint。工程驗證只接受 synthetic fixtures，產物保持 `engineering_only`。
