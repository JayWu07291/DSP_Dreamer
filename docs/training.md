# 統一訓練控制

`tools/train.py` 管理 A、B、second、third 四個訓練子階段。舊的 `train-tokenizer.py`、`train-dynamics.py`、`train-agent.py` 轉交相同入口。訓練器、loss、模型架構及 gate 評分器沿用 #24–#27。

本文件描述工程入口，不授權正式 GPU 工作。正式測速、訓練與品質證據由 #31–#33 執行。

## 預算與測速

| 帳目 | 上限 | 用途 |
| --- | ---: | --- |
| preflight | 2 小時 | 四個子階段的真實 loader、完整 loss、累積與 optimizer 測速 |
| A | 4 小時 | Tokenizer |
| B | 16 小時 | Dynamics |
| second | 6 小時 | 任務條件微調 |
| third | 4 小時 | 想像訓練 |

總計 32 小時，包含初始化、驗證、checkpoint 儲存及失敗重跑。`runs/training-budget.json` 是唯一累計帳本，檔鎖拒絕並行命令。不能刪除帳本、回復舊副本或以新目錄重置額度。Checkpoint 內的帳本快照只供追溯，恢復一律採磁碟上最新帳本。

首次執行匯入既有 `runs/tokenizer-budget.json`，若本機沒有該檔則使用 `docs/issue-24-results.json` 保存的同份紀錄，合計 2305.2320443573 秒仍歸 A。另匯入可用的 `runs/dynamics-budget.json`。#25 兩次 GPU smoke 合計 120.031 秒歸 preflight，來源見 `training-history.json`。這些用量不因工程／正式分工修訂而消失。已匯入的來源若改變，入口拒絕執行，必須先核對歷史紀錄。

`benchmark` 必須穿過完整訓練器四次更新，順序為 32、32、32、80 steps，CUDA 同步後計時。正式模式要求真實資料、固定架構、BF16 及上游合格 gate。Synthetic 與 CPU 測速只存在隔離測試帳本，不可成為正式計畫。

更新上限為 `floor(剩餘階段秒數 × 0.9 ÷ 平均更新秒數)`，其餘約 10% 留給驗證與儲存。`benchmark --updates N` 只能再縮減上限。測速權重不接入正式訓練，正式訓練從同一來源與 seed 初始化，使用換算後的 warmup／cosine 排程。

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

每 1800 累計秒在更新邊界存檔並執行固定 validation，A 為名單前八張，其他階段為前四個預測序列；second／third 另評估固定前 32 個 validation transitions 的 policy／reward。Python、NumPy、CPU 與 CUDA RNG 在 validation 前後保存還原，未完成 validation 的排程會於恢復後重試。小樣本報告不能併成完整 gate。

步數或時數先到就停止更新。完整候選 gate 會在更新結束後排程，使用相同剩餘階段預算；時間不足便保持 pending。已開始的原生檔案寫入會完成以保全 checkpoint，其耗時照實計費，不啟動下一次更新。更新失敗不會把部分 AdamW 狀態或已推進的 RNG 升為新恢復點。

## Gate 與退路

A 執行 200 圖重建，B 執行 200 段配對預測，second／third 執行同一候選的完整預測及 reward/policy gate。小樣本報告不授權下一階段。缺人工判讀、證據不足、資料錯誤、非有限 loss 或 failed gate 都不能取得依賴階段資格。

人工判讀完成後，使用原候選 checkpoint 和該次 gate 目錄的 metrics／recipe 執行 `score`。入口核對 checkpoint 的帳本身分、階段和已登錄完整評估的檔案指紋。`final-*.pt` 是正常完成時的最新恢復點；`candidate-*.pt` 才是自動完整 gate 的評估對象，不能混用兩者的檔案 hash。人工判讀後的 CPU `score`／`score-prediction`／`export` 另計，即使 GPU 預算耗盡仍可完成，且不增加 GPU 額度。

`select_candidate` 預設保留合格第二階段。第三階段未啟動、不合格或沒有開發改善時仍回傳第二階段；只有外部 development 配對比較已確認改善，且第三階段自身合格時，才以 `third_improved=True` 選第三階段。工程 gate 永不產生合格退路。
