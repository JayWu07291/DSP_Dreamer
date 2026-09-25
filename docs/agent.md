# 任務條件微調與品質評估

Issue #26 的入口載入第一階段 dynamics checkpoint，凍結 tokenizer，微調 dynamics 與新增的 policy/reward heads。工程測試使用合成錄製及正式 compiler、loader，產物標為 `engineering_only`。正式第一階段品質由 #31 驗收，第二階段訓練與候選資格由 #32 驗收。目前沒有合格的第二階段候選，也沒有啟動正式訓練。

## 模型與監督

沿用 action_catalog_v4 的完整 `ACTION_CODEC`，在載入權重前核對版本、21 維順序、scan codes、121 類 mouse、3 類 wheel 與量化設定。`Agent` 以 17 維 one-hot 經 learned embedding 形成一個 query，讀取 dynamics 最後一層的 image、action、signal 與 register tokens。這沿用 v1 原型的單向 cross-attention；世界模型不接受 task 或 agent 表示，沒有反向注意 agent 的路徑。每個 head 使用一層 GELU MLP，輸出距離 0…8 的目標。具特權狀態只供資料標籤與評分。

影格 `z_t` 搭配進入它的 `a_(t-1)`，第一個 context 影格使用 no-op。當前 `a_t` 只作監督目標，不送入同一步的 policy 輸入。提示切換保留觀測與動作歷史；MTP 只保留起點到目標之間都有效且同 task 的位置。Padding、invalid、非法動作及非法 scalar reward 不計 loss。兩個端點 task 相同，但途中曾切換的目標也會排除。

Reward 使用 255 個對稱 symexp support，從 `symexp(-20)` 到 `symexp(20)`，在 reward 原單位線性分配到相鄰兩格，輸出期望也在原單位計算。這與先對 scalar 做 symlog 再求平均的表示不同。依據為 [Dreamer 4 §3.3](https://arxiv.org/html/2509.24527v1#S3.SS3) 與 [Dreamer 3 TwoHot 實作](https://github.com/danijar/dreamerv3/blob/main/embodied/jax/outs.py)。

`policy_action` 的控制輸出會在互斥群組保留 logit 最大的 active 控制，同值取 catalog 最前者。離線評分使用原始 threshold/argmax 結果，保留禁止組合率，不用修正後動作提高品質分數。

## 抽樣、訓練與恢復

每個 update 各取一半 uniform 與 relevant train sequences，relevant 資格依任一節點完成判定，包括非 active 完成與背景里程碑。Uniform 只算原有 shortcut dynamics loss；relevant 只算 policy/reward MTP loss。Scalar reward 直接讀 loader，不因片段 relevant 而改成 1。兩類各自按抽樣 sequence 數正規化，policy/reward 按合法 MTP 目標數正規化。

正式配方保持三次 32-step、一次 80-step，microbatch 2、accumulation 8，或已核准的 1/16。Dynamics LR 為 1e-5，新增參數為 1e-4；AdamW、5% warmup、cosine 衰減及 norm clipping 沿用 #7。Tokenizer 一律 eval 且無梯度。

Checkpoint 保存完整世界模型及 agent 權重、optimizer、配方、進度、Python/NumPy/PyTorch/CUDA RNG、來源 checkpoint 路徑/checksum、凍結資料與 gate 證據。恢復不能改 updates 或資料身分。每 30 分鐘存檔並使用 #25 的固定前四個 validation 預測序列檢查；候選仍須另跑完整 gate。每個 checkpoint 的累計執行上限為六小時。跨程序、失敗重跑、評估與全階段 32 小時的統一預算管理由 #28 承接；此入口不宣稱已完成該項驗收。

## 正式入口

以下命令只有在 #31 的同源重建與預測證據完整通過後才能執行。`100` 僅示例，正式 updates 必須由完整 loader/loss 測速决定。第一階段的 `reviewed-gate.json` 必須包含完整人工判讀。

```powershell
.venv/Scripts/python.exe tools/train-agent.py train --stage-one runs/dynamics-v1/final-100.pt --prediction-dir runs/prediction-v1 --prediction-gate runs/prediction-v1/reviewed-gate.json --updates 100 --output runs/agent-v1
.venv/Scripts/python.exe tools/train-agent.py train --checkpoint runs/agent-v1/step-40.pt --output runs/agent-resumed
.venv/Scripts/python.exe tools/train-agent.py evaluate --checkpoint runs/agent-v1/final-100.pt --output runs/agent-metrics
.venv/Scripts/python.exe tools/train-agent.py predict --checkpoint runs/agent-v1/final-100.pt --output runs/agent-prediction
.venv/Scripts/python.exe tools/train-agent.py score-prediction --checkpoint runs/agent-v1/final-100.pt --metrics runs/agent-prediction/metrics.json --judgments runs/agent-prediction/judgments.json --output runs/agent-prediction/reviewed-gate.json
.venv/Scripts/python.exe tools/train-agent.py score --checkpoint runs/agent-v1/final-100.pt --metrics runs/agent-metrics/metrics.json --prediction-dir runs/agent-prediction --prediction-gate runs/agent-prediction/reviewed-gate.json --output runs/agent-gate.json
```

入口重新計算上游 gate，核對 checkpoint、recipe、凍結資料及實作 checksum。來源必须為第一階段且已有更新，工程 checkpoint、模擬 passed、缺證據及不同來源均不能授權正式微調。工程測試直接使用 Python API；CLI 不提供跳過 gate 的旗標。保留被引用的 `.pt` 與 `.pt.json`，來源修改後恢復會拒絕。

## 評估與分母

Reward 使用 validation 完整有效回合的所有合法 10 Hz transitions，每個只計一次；故障前綴不補分母。Policy 使用合法 relevant 64-step 視窗聯集，重疊區間只計一次，不因訓練 short/long 長度改變。兩者都只評距離 0。每個被測影格使用最多 64 個連續合法歷史觀測，跨提示保留歷史，以固定來源 seed 產生 signal=0.1 的擾動；不跨回合或非法區間。

Reward 期望 ≥0.5 為正，逐 16 微任務列 N、正例、TP/FP/FN/TN、precision、recall、PR-AUC 與基率。PR-AUC 使用非插值 average precision，同分視為同一 threshold。每任務 precision/recall 均須 ≥80%；無正例或 precision 未定義為 `insufficient_evidence`。等待與 scalar reward=0 的非 active 完成另列 FP。±1 步匹配只作診斷，在相同回合及未切換的 task 區間內依最短距離、最早時間一對一匹配。

Policy 的 binary 機率 ≥0.5；mouse/wheel argmax 同分取最小類別。有正例控制才列入 macro-F1，須 ≥0.60；全部 21 個控制皆列計數，無正例明列缺项。非零 mouse/wheel 子集各須 exact-class accuracy ≥50%，且比 train task-conditioned 眾數高至少 10 百分點。Baseline 從全部合法 train transitions 建立，含 no-op，不讀 validation 或 offline-test。兩邊使用相同非零子集與分母，缺 baseline 不刪掉樣本冒充通過。

另列逐任務 policy 指標、joint action NLL、no-op 比例及原始禁止組合率。零目標機率的 NLL 在 JSON 記為字串 `infinity`，另列筆數，不暗中 clamp；該情況不能通過。每個評估 transition 保存來源 artifact、模型索引、原始 transition indices、預測與監督值，可重算指標。

`evaluate` 先輸出 reward/policy 報告，dynamics 保持 pending。`predict` 直接讀同一第二階段 checkpoint 的 dynamics，沿用 #25 的 200 序列、1/5/15 步、配對 baseline 與人工判讀。`score` 重算三項 gate 並核對同一 checkpoint；只有正式產物且三項都 passed 才會令 `qualified=true`。工程資料即使數值達標，仍為 `engineering_only`。

驗證命令與各項證據見 [Issue #26 工程驗證](issue-26-validation.md)。
