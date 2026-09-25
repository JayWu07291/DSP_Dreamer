# Issue #25 工程驗證

2026-09-25，dynamics 工程路徑已打通，正式第一階段 B 尚未啟動。#24 的重建 gate 仍為 `failed`，所以 200 個真實 validation 序列的品質評估及人工判讀尚未執行，不能將 #25 的全部品質條件標成通過。

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

本次共執行兩次合成 GPU 驗證，合計 120.031 秒；第二次包含審查修正後的實作。沒有消耗正式第一階段 B 的訓練額度。

[完整機器結果](issue-25-results.json)保留四次更新的 loss、抽樣、模型設定、程式 checksum 及恢復結果。原始檔在 `runs/issue-25/gpu-smoke-final/report.json`，內容 ID 為 `f897f46d12498bfa3a197795d01d9e662846bc26910321e8bfb070eda52b50d5`。合成 checkpoint、錄製、dataset、index 及重跑腳本保留在同一目錄，不納入 Git。

可從 repo 根目錄，以新的輸出位置重跑：

```powershell
.venv/Scripts/python.exe runs/issue-25/gpu-smoke-final/reproduce.py runs/issue-25/gpu-smoke-rerun
```

此腳本只使用合成 fixture，不能轉成正式 checkpoint。正式真實資料測速仍須等 tokenizer 重建 gate 通過。

## 回歸檢查

完整 `pytest -q` 為 166 passed，耗時 191.67 秒。之後補測改善恰好 10% 的浮點邊界，改以等價的 `correct_mean <= 0.9 * baseline_mean` 判定；最新 dynamics 單檔五項再次通過。`mypy dsp_dreamer tools/train-dynamics.py` 的 25 檔通過。LPIPS 的 torchvision 舊 pretrained 參數仍會發出既有警告，未變更 metric、權重或品質門檻。

## Standards

獨立審查沒有發現 repo 文件的硬性規範違反。互斥動作規則重複屬判斷性 smell，已改為共用 `forbidden_buttons`；評估可能誤標舊實作身分的風險，已用實作 checksum 核對及變動拒絕測試修正。複核沒有剩餘程式 finding。

## Spec

獨立審查確認時間對齊與自由預測沒有未來真圖洩漏。正式評分原先缺少 checkpoint／recipe 綁定，現已核對真實 checkpoint、重建 gate、凍結身分及實作；合成報告只回傳 `engineering_only`。16 小時預算現在由 Windows 檔案鎖保護，並以另一程序驗證拒絕行為。複核沒有剩餘程式 finding。

Standards 0 項未解決，Spec 0 項未解決。實際模型品質 gate 仍待上游通過後執行，不屬於已完成的工程測試結果。
