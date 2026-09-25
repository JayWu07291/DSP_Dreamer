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
| 恢復及正式入口隔離 | 恢復後下一次 loss、樣本與全部模型權重逐值一致；工程 checkpoint、模擬 passed、不同來源、缺列或重複列被拒；合併 gate 不會讓工程產物 qualified |

## 執行方式

```powershell
.venv/Scripts/python.exe -m pytest tests/test_agent.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train-agent.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe tools/train-agent.py --help
```

模型整合測試使用 CPU、float32、width 32、4 heads，其餘 8 blocks、8 registers、64×32 latents 與 17 任務保持不變。原生 RGB 仍為 640×360。四項新增測試涵蓋模型、訓練恢復、評分邊界與完整串接。這些證據驗證工程行為，沒有量測正式 width 512 的第二階段 GPU throughput 或收斂。

四項新增測試通過；完整回歸為 **171 passed**，耗時 317.25 秒，沒有失敗或跳過。`mypy` 檢查 28 個檔案通過。CLI help 與 `git diff --check` 也通過。測試中的 numcodecs／torchvision 警告來自既有依賴的棄用提示。

## Standards

獨立審查未發現違反 AGENTS.md、CONTEXT.md 或相關 ADR。初次審查指出 policy 合法化重寫了禁止組合；已改為重用 `forbidden_buttons`，移除固定控制索引，並重跑該模型／動作測試。

## Spec

獨立審查未發現可確認的 #26 規格偏差。核對 checkpoint 與 gate 來源、codec、MTP、抽樣、reward 分母、policy 配對 baseline 及同一 checkpoint 的三項 gate。Policy 的逐任務數字是報告，不額外增加每個 task 都必須有非零 mouse/wheel 的門檻。

審查結果：Standards 一項判斷性重複規則已修正，零項待處理；Spec 零項待處理。基準為實作前的 `fa3e8d3`。

正式 reward/policy/dynamics 品質均未執行，狀態為未驗證；現有第一階段尚未取得 #31 的合格 checkpoint。此交付不啟動 #32／#33，也不揭露 offline-test 模型結果。跨階段統一預算與停止規則的工程驗收仍屬 #28。
