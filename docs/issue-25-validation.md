# Issue #25 工程驗證

2026-09-25，依 [#12 的工程／正式驗收分工](https://github.com/JayWu07291/DSP_Dreamer/issues/12)及 [#25 修訂後要求](https://github.com/JayWu07291/DSP_Dreamer/issues/25)，五項工程驗收均有對應實作與證據。正式 A／B 訓練與實際模型品質驗收由 [#31](https://github.com/JayWu07291/DSP_Dreamer/issues/31) 執行。現有 tokenizer 重建 gate 仍為 `failed`，正式第一階段 B、200 個真實 validation 序列的模型品質評估及人工判讀均未執行。

## 修訂後逐項核對

| #25 要求 | 工程驗收證據 | 結果 |
| --- | --- | --- |
| 1. 前階段 checkpoint、tokenizer 凍結及固定架構 | 正式架構 GPU smoke；CPU 正式 compiler／loader 整合更新與恢復；所有 tokenizer 權重與 gradient 狀態核對 | 通過 |
| 2. Shortcut forcing 及 v4 checkpoint 契約 | x-prediction、1/4／1/2 step、四次 forward、context signal 0.1；舊 17／18／20 維、順序與量化不符拒載；v4 恢復一致 | 通過 |
| 3. 小樣本完整流程與自由預測 | 合成 evidence 經正式 compiler、loader、完整 loss 與 checkpoint 銜接；第 1／5／15 步預測、動作影響、因果性及凍結證據 | 通過 |
| 4. 固定名單與品質評分工具 | 凍結名單 200 段、四類各 50 的身分核對；整合匯出 PNG／指標；200 筆可控評分資料驗證 10%、80%、70% 門檻及未達標／證據不足 | 通過 |
| 5. 配對分母、工程標記與正式入口 gate | 逐 baseline 對稱排除零誤差／無動作差異；缺類別及缺判不通過；工程結果維持 engineering_only；failed、pending、不同 tokenizer／凍結身分及偽改 passed 均拒絕 | 通過 |

上述第 4 項的 200 筆可控評分資料不是真實模型品質結果。GPU 合成 smoke、CPU 預測匯出、評分 fixture 與正式凍結名單分別留證，不相互冒充。

[工程結案結果](issue-25-closeout.json)以 `status=engineering_only`、`engineering_checks_status=passed` 分開記錄用途與檢查結果，並引用原始 GPU 報告的封印和 checksum。原始 smoke 報告的 `status=passed` 僅表示當時工程檢查通過；原始封存內容保留，不改標為正式品質通過。

## 已驗證範圍

| 項目 | 結果與範圍 |
| --- | --- |
| 前階段銜接與凍結 | 讀取 tokenizer checkpoint；dynamics 更新與恢復前後，tokenizer 全部權重完全一致且無 gradient |
| 正式模型設定 | RTX 5070 使用 width 512、8 blocks、8 heads、8 register tokens、第 4／8 block temporal attention、64-step context |
| 完整 loader／loss | 合成錄製經 FFV1 封存、正式 compiler、TrainingIndex 與 10 Hz 模型視圖，再計 flow／bootstrap loss 及 AdamW 更新 |
| 訓練配方 | BF16、activation checkpointing、microbatch 2、accumulation 8；依序 32、32、32、80-step 更新 |
| Checkpoint 恢復 | 從第 3 步恢復，第 4 次更新的抽樣、loss、grad norm、LR 及全部 dynamics 權重與不中斷執行完全一致 |
| 動作條件預測 | 同 generation seed，只改 B 鍵，生成的第 1／5／15 步均改變；較晚動作及未來影格不影響較早輸出 |
| 預測評分 | CPU 整合測試匯出正確動作、no-op、打亂及 copy-last 的 1／5／15 步 PNG、來源、MSE／LPIPS 與區域 LPIPS；驗證 next observation 索引為 130／138／158 |
| 拒絕條件 | 舊 17／18／20 維、控制順序、codec 不符、禁止組合、實作 checksum 變動、重新標成正式的 smoke 報告均拒絕；並行預算程序會被檔鎖拒絕 |
| 正式訓練 gate | 對現有 64-token checkpoint 及人工判讀的 failed gate 執行 CLI，確實在建立訓練輸出目錄前拒絕 |

## GPU 合成 smoke

最終驗證共 57.844 秒，包含 fixture 產生、一次 tokenizer 更新、dynamics 四次更新、第 4 步恢復重跑、自由預測及 checkpoint 儲存。PyTorch peak allocated 為 1.987 GiB，peak reserved 為 2.986 GiB。這兩個值不是整卡顯存使用量，合成 fixture 的時間也不是真實資料 throughput。

先前共執行兩次合成 GPU 驗證，合計 120.031 秒。此次收尾沿用既有產物，沒有新增 GPU 訓練；工程用量紀錄保留，不因工程結案而歸零。正式第一階段 B 尚未啟動。

[完整機器結果](issue-25-results.json)保留四次更新的 loss、抽樣、模型設定、程式 checksum 及恢復結果。原始檔在 `runs/issue-25/gpu-smoke-final/report.json`，內容 ID 為 `f897f46d12498bfa3a197795d01d9e662846bc26910321e8bfb070eda52b50d5`。合成 checkpoint、錄製、dataset、index 及重跑腳本保留在同一目錄，不納入 Git。

GPU smoke 直接驗證 trainer、model.rollout 與 decoder，沒有執行完整 `evaluate_prediction`。該次保存的 evaluator SHA-256 為 `fb764ada0095bfacd66a9236737ccb30b4a7e91b8bf25af20f31a79dd4074e78`；之後的 10% 浮點邊界修正由最新 CPU 回歸驗證。收尾確認 dynamics、dynamics_training 與 CLI 的 checksum 仍與 GPU 報告相同，不能將舊 GPU 報告解讀成最新版 evaluator 的 GPU 驗證。

可從 repo 根目錄，以新的輸出位置重跑：

```powershell
.venv/Scripts/python.exe runs/issue-25/gpu-smoke-final/reproduce.py runs/issue-25/gpu-smoke-rerun
```

此腳本只使用合成 fixture，不能轉成正式 checkpoint。正式真實資料測速仍須等 tokenizer 重建 gate 通過。

## 收尾證據核對

正式評估輸入 ID 為 `f8705e40e8906a15d20075fbfbd9857a74a1d0636ab8c1aadfeaf20ff3a6e358`，資料凍結 ID 為 `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f`。`read_frozen_evaluation` 核對協定、所有凍結小型檔案、來源程式 checksum 及相互引用；預測名單仍為 movement／ui／interaction／waiting 各 50，沒有重新抽樣或修改標註。

Git 保存的 GPU 報告與本機原報告逐位元組一致，報告封印、TrainingIndex ID、重跑腳本 checksum 與合成 checkpoint 均核對通過。Checkpoint 為 380,366,923 bytes，SHA-256 `7c9874f18a8fe257efa297a096550c6386f6c5de1b5822bc4982fb84e3ef9a74`。大型原始產物及重跑腳本只保留於上述本機目錄；Git 提供完整機器報告與 CPU 整合測試，未宣稱大型產物已隨 repo 發布。

64／96-token 的重建評分重新計算後皆與保存的 gate 相同，各為 0／15 正確、無缺判、failed，且 checkpoint hash 相符。使用現有 64-token 證據再次呼叫正式 train CLI，確實回報「重建 gate 未通過」，未建立訓練輸出目錄。此次未重讀完整真實影像資料集或揭露 offline-test 模型結果。

## 回歸檢查

此次完整 `pytest -q` 為 167 passed、6 個既有 warnings，耗時 276.08 秒；dynamics 單檔 6 項通過，耗時 36.28 秒。`mypy dsp_dreamer tools/train-dynamics.py` 的 25 檔通過。LPIPS 的 torchvision 舊 pretrained 參數仍會發出既有警告，未變更 metric、權重或品質門檻。

新增核對涵蓋整體恰好 80%／低於 80%、前三類各自恰好 70%／低於 70%，以及三類對三個 baseline 各自未達 10% 時仍判失敗。既有 10% 浮點邊界以等價的 `correct_mean <= 0.9 * baseline_mean` 判定。另測三個 baseline 的無動作差異分母為零、缺等待類別、重建 gate 的 failed／pending、不同 tokenizer／凍結身分及重封為 passed 均拒絕。這些可控分數與判讀只供測試，不是人工模型品質證據。

## Standards

獨立審查沒有發現 repo 文件的硬性規範違反。互斥動作規則重複屬判斷性 smell，已改為共用 `forbidden_buttons`；評估可能誤標舊實作身分的風險，已用實作 checksum 核對及變動拒絕測試修正。此次複核另指出 GPU 報告晚於部分修正、早於評分浮點修正的界線需明載，已補上原 hash 與實際驗證範圍。複核沒有剩餘程式 finding。

## Spec

獨立審查確認時間對齊與自由預測沒有未來真圖洩漏。正式評分原先缺少 checkpoint／recipe 綁定，現已核對真實 checkpoint、重建 gate、凍結身分及實作；合成預測評分的 gate 只回傳 `engineering_only`。16 小時預算現在由 Windows 檔案鎖保護，並以另一程序驗證拒絕行為。此次複核指出原始 GPU smoke 的 `passed` 容易與品質通過混淆，已新增獨立工程結案結果及用途說明，保留原始報告。複核沒有剩餘程式 finding。

Standards 0 項未解決，Spec 0 項未解決。實際模型品質 gate 仍待上游通過後執行，不屬於已完成的工程測試結果。
