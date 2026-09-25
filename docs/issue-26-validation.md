# Issue #26 工程驗證

本紀錄對應 2026-09-25 修訂後的 [#26](https://github.com/JayWu07291/DSP_Dreamer/issues/26)。測試以合成錄製經正式 compiler、TrainingIndex、ModelView、tokenizer checkpoint、第一階段 dynamics 更新，再進第二階段；沒有用重新初始化的世界模型代替階段銜接。

## 驗收對照

| 要求 | 可重跑證據 |
| --- | --- |
| 同源 checkpoint、凍結 tokenizer、單向 attention | `test_stage_one_loader_finetuning_resume_and_gate_rejection` 比較初始 dynamics 權重與來源、更新後變化及 tokenizer 不變；`test_agent_causality_masks_twohot_and_legal_actions` 驗證 task 改變 policy 但不影響世界模型，歷史可跨提示 |
| v4/21 完整 codec、symexp twohot、MTP 0…8 | codec 改寬度、順序或 mu 在權重讀入前拒絕；twohot 期望還原 -1/0/0.5/1/10；MTP 核對九種距離、跨 task、padding、非法類別及梯度範圍 |
| 50/50 loss 與非 active 完成 | 真正 loader 的 uniform/relevant 各半；長 fixture 只有非 active 完成，relevant 可取樣但 scalar reward 全零 |
| Reward 指標與缺證據 | `test_reward_and_policy_metrics_use_exact_paired_denominators` 核對 TP=4、FP=1、FN=1、TN=4，P/R=.8、AP=.74；另驗證 failed、缺正例與未定義 precision |
| Policy baseline、門檻與缺樣本 | Digit1 納入 F1；macro-F1=.60、非零 accuracy=.50、眾數差距恰為 10 百分點；缺 baseline、空子集、零機率 NLL 均不能通過 |
| 完整資料與三項 gate | `test_continuous_validation_relevant_union_and_stage_two_dynamics` 的 17 個重疊 relevant 視窗合為 80 個 transitions；故障 validation 不補 reward 分母；同一 agent checkpoint 可執行 #25 預測評估並併入完整報告 |
| 恢復及正式入口隔離 | 恢復後下一次 loss、樣本與全部模型權重逐值一致；`test_stage_one_gate_checks_reconstruction_prediction_and_identity` 逐一核對缺重建、缺預測、重建 failed/pending、錯 tokenizer、錯凍結來源及錯預測 checkpoint 的拒絕；合併 gate 拒絕工程／正式標記不一致 |

## 執行方式

```powershell
.venv/Scripts/python.exe -m pytest tests/test_agent.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train-agent.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe tools/train-agent.py --help
```

模型整合測試使用 CPU、float32、width 32、4 heads，其餘 8 blocks、8 registers、64×32 latents 與 17 任務保持不變。原生 RGB 仍為 640×360。五項測試涵蓋模型、訓練恢復、評分邊界、完整串接及上游 gate 拒絕。上游拒絕案例使用沒有模型權重、無法執行 tokenizer 的中繼資料 fixture，只供走到各失敗分支。這些證據驗證工程行為，沒有量測正式 width 512 的第二階段 GPU throughput 或收斂。

五項 agent 測試通過，耗時 38.00 秒；完整回歸為 **172 passed**，耗時 309.30 秒，沒有失敗或跳過。`mypy` 檢查 28 個檔案通過。CLI help 與 `git diff --check` 也通過。完整回歸有 10 則既有 torchvision 棄用警告，啟動時另有 numcodecs 棄用提示。

## Standards

獨立審查未發現違反 AGENTS.md、CONTEXT.md 或相關 ADR。初次審查指出 policy 合法化重寫了禁止組合；已改為重用 `forbidden_buttons`，移除固定控制索引，並重跑該模型／動作測試。

## Spec

結案複查發現合併 gate 未核對 dynamics 證據的工程／正式標記，可能把工程報告的數值達標當成正式品質通過。已先以真實 loader 整合測試重現，再要求 metrics、recipe 與候選的標記一致，正式合併改用 dynamics 的實際 `status`。另補上游 gate 各拒絕分支的測試，避免所有案例都只撞到工程 checkpoint 的第一道檢查。

最終獨立審查核對 checkpoint 與 gate 來源、codec、MTP、抽樣、reward 分母、policy 配對 baseline 及同一 checkpoint 的三項 gate，沒有剩餘的工程驗收問題。Policy 的逐任務數字是報告，不額外增加每個 task 都必須有非零 mouse/wheel 的門檻。Standards 與 Spec 均零項待處理；基準為實作前的 `fa3e8d3`。

## 結案證據

可機讀摘要及 checksum 見 [issue-26-closeout.json](issue-26-closeout.json)。原始合成錄製、checkpoint、完整評分報告和測試 XML 保留在本機 `runs/issue-26/`，不納入 Git：

- `closeout-tests-20260925/test_stage_one_loader_finetuni0/`：實際模型推論六個 reward transitions；reward/policy 為證據不足，dynamics 為 pending。
- `closeout-tests-20260925/test_continuous_validation_rel0/`：八十個 transitions 的受控 policy/reward 機率評分，搭配同一 checkpoint 的實際 dynamics 預測；reward 為證據不足、policy 為 failed、dynamics 為 engineering_only。

兩組完整 gate 均為 `engineering_only`、`qualified=false`。另以 CLI 實際嘗試恢復工程 checkpoint，確認建立輸出目錄前即拒絕。正式凍結檔與來源 hash 已重新核對，預測序列仍為四類各 50 段。

正式 reward/policy/dynamics 品質均未執行，狀態為未驗證；現有第一階段尚未取得 #31 的合格 checkpoint。此交付不啟動 #32／#33，也不揭露 offline-test 模型結果。跨階段統一預算與停止規則的工程驗收仍屬 #28。
