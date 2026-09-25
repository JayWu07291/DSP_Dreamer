# Issue #28 工程驗證

本紀錄依 [#28 的 2026-09-25 結案範圍](https://github.com/JayWu07291/DSP_Dreamer/issues/28)驗證訓練控制、記帳、定期存檔與停止機制。測試從合成錄製經正式 compiler、TrainingIndex、ModelView、tokenizer、dynamics、任務微調，再進想像訓練。所有產物只供工程驗證，未執行 #31–#33 的正式 GPU 測速或訓練。

## 驗收對照

| 要求 | 工程證據 |
| --- | --- |
| 完整 loader/loss 換算更新數，分項及總時數上限 | `benchmark` 穿過四個真實 trainer，各執行四次更新；正式模式只接受真實資料及 CUDA。手算 14300 秒、10/10/10/30 秒四次測速得到 858 updates。帳本固定 2/4/16/6/4 小時，共 115200 秒 |
| Batch 2/8、三短一長、OOM 只改 1/16 | 正式配置沿用既有 trainer；工程計畫記錄 2/2/2/3-step 縮短 context。帳本測試覆蓋未 OOM 拒絕 1/16、2/8 OOM 後拒絕再跑 2/8、1/16 再 OOM 停止；重測不可增加原上限 |
| Optimizer、各組 LR、schedule 與 clip | 沿用 #24–#27 的 AdamW、bias/norm 不衰減、clip=1。整合測試核對 optimizer 已有狀態、betas/epsilon、各組最後 LR 為 peak 的 10%；原有恢復回歸核對下一次 loss、抽樣與權重相同 |
| 定期驗證、存檔、完整 gate | 受控時鐘在四階段觸發 1800 秒排程，真正輸出重建／預測 PNG、metrics、recipe、checkpoint；second/third 同時執行固定 32 個 policy/reward transitions。結束後跑同一候選的完整 gate 路徑，小樣本明確不能合併成合格 gate |
| 失敗、pending、非有限 loss 與退路 | 真 tokenizer 的 LPIPS 參數污染產生非有限 loss，另以非法模型視圖驗證資料錯誤停止。失敗保留完整恢復點，撤銷當前 gate；待驗證／失敗／證據不足均不解鎖下游。獨立 fixture 驗證合格第二階段退路及單獨 predict 不撤銷它 |
| 中斷、重跑計費、時數／步數上限與 codec | Validation 後中斷，再從保存的 optimizer/RNG/control 恢復；已花時數及已嘗試步數保留。真 trainer 進入時數先到路徑後不更新，留下 budget_exhausted 報告。強制終止紀錄重啟補計一次。拒絕 17/18/20 維、逆序 controls 及錯 mu；四階段 v4 checkpoint 正常恢復 |

## 執行與產物

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_training_control.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer tools/train.py tools/train-tokenizer.py tools/train-dynamics.py tools/train-agent.py
.venv/Scripts/python.exe -X utf8 -m pytest -q
git diff --check
```

四階段整合模型使用 CPU float32、width 32、4 heads，RGB 維持 640×360、64×32 latents、17 任務與 21 維動作。工程更新 context 為 2／3 steps，prediction validation 仍讀 64-step 歷史及預測 15 steps，imagination rollout 仍為 15 steps。此測速不代表正式 width 512、2/8、32／80-step 的 GPU throughput。

單獨四階段整合測試通過，耗時 282.69 秒。停止／帳本三項測試通過，最新一輪耗時 11.25 秒。完整回歸為 179 passed，耗時 447.19 秒，無失敗或跳過；18 則既有 torchvision 棄用警告，啟動時另有 numcodecs 棄用提示。Mypy 檢查 34 個檔案、CLI help 與 `git diff --check` 均通過。完整回歸結果與產物指紋見 [機器摘要](issue-28-closeout.json)。

可追溯工程 smoke 位於 `runs/issue-28/full-suite/test_controlled_pipeline_uses_0/`。A 的短評估為 insufficient_evidence，B／second／third 為 engineering_only；所有候選 qualified=false。控制器的 run 報告均標為 engineering_only。門檻 fixture 的 passed 僅用來驗證停止／退路邏輯，沒有正式模型資格。

## 既有預算

以隔離帳本匯入本機歷史紀錄，A 保留 2305.2320443573 秒，preflight 保留 #25 兩次 GPU smoke 共 120.031 秒。餘額依序為 preflight 7079.969、A 12094.7679556427、B 57600、second 21600、third 14400 秒。匯入重跑不重複收費，已匯入檔案若改變會拒絕。正式帳本未啟動，本次 CPU 測試的虛擬時鐘不混入正式 GPU 用量。

未收尾 attempt 會保守計到下一次重啟，最多扣完原保留額度。原生 checkpoint 寫入若跨越 deadline，會完成寫入並照實收費。這兩項行為避免少計用量，可能讓實際剩餘額度比已知 GPU 時間更少。

## Standards

獨立審查未見 AGENTS.md、CONTEXT.md 或 ADR 違規。初查發現部分更新不應升為最新 checkpoint，以及 CLI 接受無效 stage/command 組合；已修正並驗證。複核沒有剩餘問題。

## Spec

獨立審查指出 second/third 定期驗證漏 policy/reward、評分可登錄未綁帳本的候選，以及純 CPU 判讀評分受 GPU 額度限制。已補齊小樣本評估、帳本與完整評估指紋核對、獨立 CPU 評分路徑。後續再補上失敗撤銷舊 evaluation、拒絕替換 prediction metrics，以及保留 predict 前的第二階段退路。複核剩餘零項。

審查基準為 `7b5b75af322dc6a7dea627d61f626e27669f1600`。Standards 0 項未解決，Spec 0 項未解決；正式品質、development 選模及正式訓練仍未執行。
