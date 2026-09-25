# Issue #27 工程驗證

本紀錄驗證固定任務想像訓練、checkpoint 銜接、恢復、候選匯出及 gate 拒絕行為。測試從合成錄製經正式 compiler、TrainingIndex、ModelView、tokenizer 更新、dynamics 更新與第二階段更新，才載入第三階段。所有模型產物均為 `engineering_only`，不能授權正式訓練或 development。

## 驗收對照

| #27 要求 | 可重跑證據 |
| --- | --- |
| 凍結 tokenizer、dynamics、reward、prior | `test_stage_two_imagination_resume_export_and_rejections` 核對初始 agent 與第二階段逐值一致，更新後只改 policy／value，凍結 hash 不變；故意修改 reward／prior 後拒絕存檔或讀取 |
| 固定 task、15 steps、return、PMPO、KL、value | 同一整合測試核對 16 個 state 共用 task；`test_imagination_objective_and_action_contract` 使用手算 lambda-return、正負例不等量、空集合及非對稱 KL 範例，value 沿用已測 symexp twohot |
| 更新、codec、恢復與匯出 | 合法分布抽樣經正式 decode／encode 往返；policy／value 皆更新；恢復後下一次 loss、樣本、模型和 value 權重逐值一致；候選 checkpoint 可重新載入 |
| 可追溯與拒絕不相容 | 匯出保留 data index、來源、完整 codec／catalog、配方、工具版本及評分；拒絕 17 維、錯控制順序、錯 mu、錯 horizon、變動 prior；CLI 在讀正式資料或建立目錄前拒絕工程來源及恢復 |
| 相同離線 gate | `test_continuous_validation_relevant_union_and_stage_two_dynamics[True]` 使用第三階段 checkpoint 實際評估 80 個 validation transitions 及同一模型的 dynamics 預測，匯出重算三項 gate；工程候選保持 `qualified=false` |

## 命令與界線

```powershell
.venv/Scripts/python.exe -m pytest tests/test_imagination.py tests/test_agent.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train-agent.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe tools/train-agent.py --help
git diff --check
```

整合模型為 CPU float32、width 32、4 heads，保持 8 blocks、8 registers、64×32 latents、原生 640×360 RGB、17 任務與 21 維動作。Context 在工程更新中縮短，rollout 仍固定 15 steps；長 validation 視窗另測 64-step 歷史。未測正式 width 512 的第三階段 GPU throughput、顯存或收斂。

Agent／imagination 八項整合測試通過，耗時 148.55 秒；mypy 檢查 29 個檔案通過，CLI help 與 `git diff --check` 通過。原始測試產物保留於本機 `runs/issue-27/`，不納入 Git。

完整回歸為 **175 passed**，耗時 410.34 秒，沒有失敗或跳過。共有 14 則既有 torchvision 棄用警告，啟動時另有 numcodecs 棄用提示。測試 XML、兩份候選及目前實作的 checksum 收錄於 [issue-27-closeout.json](issue-27-closeout.json)。

80-transition 第三階段候選的實際推論得到 reward `insufficient_evidence`、policy `failed`、dynamics `engineering_only`。三項 gate 合併後仍為 `engineering_only`、`qualified=false`。六個 reward transitions 的短 fixture 亦未取得資格；未執行的正式指標不填零。

## Standards

獨立審查未發現 AGENTS.md、CONTEXT.md 或 ADR 違規。初查指出驗證文件連結尚未建立，以及匯出重複重算上游 gate；已補齊文件並保留 `combine_gates` 單一驗證入口，複核剩餘零項。

## Spec

獨立審查核對真正 checkpoint 銜接、固定 task／horizon、PMPO 正負集合及 reverse KL、凍結權重、恢復、codec 與正式候選資格，沒有待處理問題。審查基準為實作前 `96e5ab0035ea661e902d7f8b8c6f246158887e76`。

正式第二階段品質尚未執行，第三階段正式訓練亦未執行。#32 的合格來源仍是 #33 的必要條件；本票工程通過不解鎖正式訓練、development 或 final。固定 imagined horizon 未建模終止機率，詳見[訓練說明](imagination.md)。統一預算管理由 #28 承接。
