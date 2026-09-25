# 統一訓練控制

`tools/train.py` 管理 A、B、second、third 四個訓練子階段。舊的 `train-tokenizer.py`、`train-dynamics.py`、`train-agent.py` 轉交相同入口。訓練器、loss、模型架構及 gate 評分器沿用 #24–#27，學習參數集中在根目錄 [training_config.py](../training_config.py)。

本文件描述工程入口，不授權正式 GPU 工作。正式測速、訓練與品質證據由 #31–#33 執行。

## 手動重訓 A

使用者確認 #31 的 756 次更新仍產生無法辨識的紋理，選擇直接重跑完整 A，並自行執行、完成後再通知 Agent。這次修改沒有啟動正式訓練，也沒有重設本機既有帳本。

先關閉 DSP，在 repo 根目錄的 PowerShell 執行：

```powershell
# 檢視全部解析後設定，不讀資料、不使用 GPU、不改帳本。
.venv/Scripts/python.exe tools/train.py A show-config

# 修改 training_config.py 後，一次完成重新測速、全新 A 訓練與評估。
.venv/Scripts/python.exe tools/train.py A run --restart
```

省略 `--output` 時使用 `runs/A-年月日-時分秒-微秒/`，避免覆寫。也可指定尚不存在的 `--output runs/A-retry-01`。`run` 在同一把帳本鎖下讀取一次資料，完成測速後釋放測速模型，再從 seed 初始化正式模型。測速權重不接入訓練。此指令不會啟動 B。

`--restart` 是明確開始新實驗：先把完整舊帳本保存到本次 log 目錄的 `previous-budget.json`，再清除該階段及歸屬該階段的前置 attempt／計畫／gate。舊 checkpoint、圖片、報告、匯入指紋與重設紀錄都保留；其他階段的用量不重設。若下游已有執行紀錄，拒絕單獨重設上游。新舊實驗的歷史總用量可以超過原單輪 32 小時，不能把封存歷史視為零用量。恢復中斷訓練要用 `train --checkpoint`，不要加 `--restart`。

### 設定檔

可先複製設定檔，再以 `--config path/to/config.py` 使用另一份配方。這是由使用者維護的本機 Python 檔案。各區的用途如下：

| 位置 | 可調內容 |
| --- | --- |
| `OPTIMIZER` | AdamW weight decay、betas、epsilon、梯度裁切、warmup 比例與最低 LR 比例 |
| `SEQUENCES` | microbatch／accumulation、短長 sequence 長度與長 sequence 頻率 |
| `STAGES['A']` | seed、LR、秒數／更新上限、masking 機率上限、MSE／LPIPS 權重 |
| `STAGES['B']` | seed、LR、秒數／更新上限、flow／bootstrap 權重 |
| `STAGES['second']` | world 與 agent LR、dynamics／policy／reward 權重及 B 的 loss 參數 |
| `STAGES['third']` | policy／value LR、horizon、gamma、lambda、PMPO alpha、KL／value 權重 |
| `RUNTIME` | 資料核對模式、前置時數、驗證間隔、測速換算比例、CPU threads |
| `TOKENIZER`／`DYNAMICS` | 顯示目前固定 v1 架構；正式入口會拒絕不相容修改，A 必須維持 64 tokens |

共同字典的參數可在各 `STAGES` 中覆寫。有效 batch 維持 16，2／8 是預設，1／16 限 OOM 後使用。正式秒數可縮減，不能超過下方階段上限。`updates=None` 依測速換算；整數只能進一步降低更新上限。資料表示、動作 codec、shortcut 算法步長、reward bins、固定評估名單及 gate 門檻仍屬模型／評估契約，不是本次調參開關。`show-config` 的 third 會列出父訓練配置的 flow/world/reward 等欄位，這些不作用於想像訓練；可調的第三階段參數以上表與 `STAGES['third']` 為準。

本次 A 預設只把 `mask_max_probability` 從 0.9 改為 0，先嘗試完整畫面重建。LR 仍為 1e-4、MSE／LPIPS 權重仍為 1／0.2、預算仍為 4 小時。這是一個待驗證實驗，沒有證據證明它已解決雜訊重建。新模型的 tokenizer 架構未改。執行中修改設定檔不影響已載入的配方；恢復時若學習參數、模型或驗證排程不同，入口拒絕混用。

### 資料核對與 log

`verify_rgb=False` 是訓練入口的新預設，依使用者提供的 `data/datasets` 不會修改這項前提，略過 RGB chunk 全量 hash、逐張解壓核對與全目錄 inventory。仍檢查 COMPLETED、metadata、parquet、Zarr metadata、資料索引／split、來源實作及七份凍結評估檔；實際取樣時才讀 RGB。一般 `open_dataset`／`TrainingIndex.open` 仍預設完整核對。若資料曾修改、搬到不可信儲存或需要完整稽核，使用 `--verify-data`。快速模式無法預先偵測尚未取用的 RGB chunk 損壞，也不宣稱驗證了它們。

本機 24 份真實資料的快速載入實測 87.06 秒，index ID 與 200 圖名單不變；先前完整 loader 為 1653.86 秒。這是 CPU 載入檢查，沒有執行訓練更新。

除 `show-config` 外，每次執行命令都建立與輸出相鄰的 `<output>.logs/`：

| 檔案 | 紀錄 |
| --- | --- |
| `config.json` | 啟動時解析的完整設定；CLI override／實際換算更新數另記在 events 的 `resolved_training_config` |
| `events.jsonl` | 每次更新的 loss 分項、LR、gradient norm、抽樣位置、耗時、剩餘時間，以及測速／驗證／checkpoint 事件 |
| `console.log` | 主程序的終端輸出、warnings 與 Python traceback |
| `status.json` | 正常退出或受控錯誤的程序狀態；不代表模型品質合格 |
| `previous-budget.json` | 只有 `--restart` 才產生的完整舊帳本 |

事件逐筆追加、flush 與 fsync，無需由 Agent 輪詢。強制終止可能來不及產生最後的 status；用已保存的 events 和 checkpoint 判斷最後進度。不要在訓練期間持續開啟會被原子替換的 `runs/training-budget.json`，Windows 的讀取 handle 曾造成替換失敗；即時觀察請看終端或 append-only log。

`run` 的主輸出包含 `plan.json`、`training/recipe.json`、`training/run.json`、各 `.pt`／`.pt.json`、`validation-*` 與 `gate/`。A 每次驗證另產生 `human-review.md`，列出前八張及含關鍵標註的原圖／重建對照；最終 `gate/` 保留完整 200 組 PNG。新增的 patch-mean 空間變化量用來發現紋理退化，不會取代人工 gate 或自動授予品質資格。

完成或出錯後，把本次輸出目錄名稱交給 Agent 即可。分析時以 `training/run.json` 判斷訓練完成狀態，以 `gate/gate.json` 與人工判讀判斷品質，並核對 log、設定與 checkpoint。

## 凍結來源相容性

#31 首次執行因 #27 的互斥群組重構與 #29 的 runner metadata 保留改動，使兩個來源實作 checksum 不符而停止。使用者其後要求修復並訓練，另存 `protocols/source-compatibility-issue31.json`，綁定原 source-freeze ID 與 `actions.py`／`dataset.py` 的精確新舊 bytes、SHA-256。原始資料、split、七份 evaluation 凍結檔案與模型門檻均保留。

正式 loader 與 `verify-data-freeze.py` 共用核對器。目前使用另存的 `protocols/source-compatibility-training.json`，承接舊紀錄並新增 immutable RGB 模式所需的 dataset／model_view／training_index 精確指紋。原始相容性檔與凍結檔不覆寫；額外修改仍拒絕。帳本會計入來源核對失敗，checkpoint 的 implementation 指紋包含相容性紀錄。這項相容性不授予模型資格，B 仍須先通過 A 的完整重建 gate。

## 預算與測速

| 帳目 | 上限 | 用途 |
| --- | ---: | --- |
| preflight | 2 小時 | 四個子階段的真實 loader、完整 loss、累積與 optimizer 測速 |
| A | 4 小時 | Tokenizer |
| B | 16 小時 | Dynamics |
| second | 6 小時 | 任務條件微調 |
| third | 4 小時 | 想像訓練 |

單輪上限總計 32 小時，包含初始化、驗證、checkpoint 儲存及失敗重跑。`runs/training-budget.json` 是唯一累計帳本，檔鎖拒絕並行命令。不能刪除帳本、回復舊副本或只換輸出目錄來重置額度；新的重訓實驗必須明確使用上述 `--restart` 並保存完整舊帳本。Checkpoint 內的帳本快照只供追溯，恢復一律採磁碟上最新帳本。

首次執行匯入既有 `runs/tokenizer-budget.json`，若本機沒有該檔則使用 `docs/issue-24-results.json` 保存的同份紀錄，合計 2305.2320443573 秒仍歸 A。另匯入可用的 `runs/dynamics-budget.json`。#25 兩次 GPU smoke 合計 120.031 秒歸 preflight，來源見 `training-history.json`。這些用量不因工程／正式分工修訂而消失。已匯入的來源若改變，入口拒絕執行，必須先核對歷史紀錄。

`benchmark` 穿過完整 loss、累積與 optimizer，CUDA 同步後計時。預設四次更新為 32、32、32、80 steps；修改 sequence 設定時，測速跑 `lcm(4, long_every)` 次以涵蓋完整週期。正式模式要求真實資料、固定架構、BF16 及上游合格 gate。Synthetic 與 CPU 測速只存在隔離測試帳本，不可成為正式計畫。

更新上限為 `floor(剩餘階段秒數 × update_fraction ÷ 平均更新秒數)`，預設比例 0.9，其餘約 10% 留給驗證與儲存。`benchmark --updates N` 只能再縮減上限。測速權重不接入正式訓練，正式訓練從同一來源與 seed 初始化，使用換算後的 warmup／cosine 排程。

預設 microbatch 2、accumulation 8。帳本有此階段的 CUDA OOM 後，只能改用 1／16，重新執行 benchmark，再用相同 `--microbatch 1` 恢復最新 checkpoint。已花時數、已嘗試更新數與原步數上限保留；重測不能增加原步數上限。1／16 仍 OOM 就停止。

## 執行與恢復

```powershell
.venv/Scripts/python.exe tools/train.py A benchmark --output runs/A-plan.json
.venv/Scripts/python.exe tools/train.py A train --output runs/A
.venv/Scripts/python.exe tools/train.py A train --checkpoint <帳本最新 checkpoint> --output runs/A-resumed
```

輸出位置必須尚未存在。B 的 benchmark／train 需 `--tokenizer`、`--reconstruction-metrics`、`--reconstruction-gate`；second 需 `--stage-one`、`--prediction-dir`、`--prediction-gate`；third 需 `--stage-two`、`--metrics`、`--agent-gate`、`--prediction-dir`、`--prediction-gate`。來源 gate 必須先經本入口的 `score` 重算並登錄帳本，來源 checkpoint 與帳本合格候選必須一致。詳細評分參數見各階段說明及 `--help`。

恢復時使用 `--checkpoint`，保留所有上游 `.pt` 和旁邊的 `.pt.json`。模型、完整 ACTION_CODEC、資料身分、實作 checksum、optimizer、schedule、RNG、目前步數、累計預算及 validation 進度一併核對。舊 17／18／20 維或控制順序、量化不符的 checkpoint 在載入權重前拒絕。舊版 checkpoint 可以作為原始證據保留，但缺少新控制狀態者不能冒充此帳本的最新恢復點。

每次更新前先記錄已嘗試更新數，因此程序在更新中被強制終止也不退回步數額度。中斷時若來不及存檔，下次從最新完整 checkpoint 恢復；其後遺失的工作仍計費。未收尾 attempt 以開始到下次重啟的 wall time 保守補計，最多扣完當時剩餘額度。這可能包含停機時間，不能把無法證實的用量當成零。

預設每 1800 累計秒或距上次驗證 50 次更新，先到者於下一個更新邊界存檔並執行 validation；可由 RUNTIME 修改，`validation_updates=0` 關閉步數條件。A 為名單前八張，其他階段為前四個預測序列；second／third 另評估固定前 32 個 validation transitions 的 policy／reward。Python、NumPy、CPU 與 CUDA RNG 在 validation 前後保存還原，未完成 validation 的排程會於恢復後重試。小樣本報告不能併成完整 gate。

步數或時數先到就停止更新。完整候選 gate 會在更新結束後排程，使用相同剩餘階段預算；時間不足便保持 pending。已開始的原生檔案寫入會完成以保全 checkpoint，其耗時照實計費，不啟動下一次更新。更新失敗不會把部分 AdamW 狀態或已推進的 RNG 升為新恢復點。

## Gate 與退路

A 執行 200 圖重建，B 執行 200 段配對預測，second／third 執行同一候選的完整預測及 reward/policy gate。小樣本報告不授權下一階段。缺人工判讀、證據不足、資料錯誤、非有限 loss 或 failed gate 都不能取得依賴階段資格。

人工判讀完成後，使用原候選 checkpoint 和該次 gate 目錄的 metrics／recipe 執行 `score`。入口核對 checkpoint 的帳本身分、階段和已登錄完整評估的檔案指紋。`final-*.pt` 是正常完成時的最新恢復點；`candidate-*.pt` 才是自動完整 gate 的評估對象，不能混用兩者的檔案 hash。人工判讀後的 CPU `score`／`score-prediction`／`export` 另計，即使 GPU 預算耗盡仍可完成，且不增加 GPU 額度。

`select_candidate` 預設保留合格第二階段。第三階段未啟動、不合格或沒有開發改善時仍回傳第二階段；只有外部 development 配對比較已確認改善，且第三階段自身合格時，才以 `third_improved=True` 選第三階段。工程 gate 永不產生合格退路。
