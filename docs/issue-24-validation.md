# Issue #24 驗證紀錄

本票交付 tokenizer、真實模型視圖訓練、checkpoint 恢復、64／96-token 對照和重建 gate 評分工具。正式 v1 固定 64 tokens；工程驗證不等於模型品質通過。

## 工程驗收核對

2026-09-25 重新核對 [#24](https://github.com/JayWu07291/DSP_Dreamer/issues/24) 與父規格 #12，五項工程要求均已完成。#24 明訂「此工程 ticket 完成不代表正式模型 gate 通過」；下表完成狀態適用於工具與驗證交付。

| #24 要求 | 已完成證據 |
| --- | --- |
| 正式架構、完整 loss 與 patch masking | `tokenizer.py`／`tokenizer_training.py` 及 GPU 配方核對原生 640×360、20×20 patches、64 tokens、32 維 bottleneck、width 512、四層 causal temporal attention、MSE + 0.2 LPIPS 與逐圖 masking。 |
| 64／96 相同步數短程對照，v1 保持 64 | 封存計畫固定 seed 2202 與各四次更新，兩組逐次資料順序相同，共用 loss、masking 與標註；正式 train 入口拒絕 96 tokens。 |
| 真實 loader、BF16、checkpointing 更新及恢復 | 兩組均完成 32／32／32／80-step 更新，恢復後 loss 與全部權重一致；checkpoint 含資料、配置、optimizer、RNG 與 checksum。 |
| 固定 200 圖、逐 task 配額、指標與辨識 gate | 兩組均完成 200 圖且 17 個 task 各至少十圖，輸出 MSE、LPIPS、UI MSE 及完整人工判讀；整體 95%／每類 90% 門檻正確判為 failed。 |
| 缺判／缺類型狀態及工程、品質界線 | `tests/test_tokenizer.py` 驗證 pending、insufficient_evidence、passed、failed；工程摘要與後續人工判讀分別封存，不以工程完成啟動 dynamics。 |

收尾另核對固定評估輸入、實作檔案 checksum、兩個對照 checkpoint、800 張 PNG 與全部封存連結，重新計算兩組人工 gate，均與保存結果一致。程式碼未改動，沿用下方已通過的完整測試與型別檢查結果。

## 本機驗證

2026-09-25 正式工程驗證通過。24 份資料集、355,853 張 RGB 經完整檔案及逐幀 checksum 核對，重建出的模型視圖與凍結 TrainingIndex 一致。RTX 5070 使用原生 640×360、width 512、BF16、activation checkpointing、完整 MSE + 0.2 LPIPS、microbatch 2／accumulation 8，沒有改用容量原型或較小資料集。

工程驗證摘要與完整身分見 [issue-24-results.json](issue-24-results.json)，保留其產生時尚未人工判讀的狀態。後續人工判讀另存 [issue-24-human-review.json](issue-24-human-review.json)，包含兩組完整判讀、逐項回覆證據與封存身分，並引用原工程摘要。完整紀錄位於 `runs/issue-24/verification/verification.json`，權重、逐次抽樣、配方、重建 PNG 和人工判讀模板保存在同目錄。大型本機輸出不納入 Git。實作版本為 `fce0e7d`，各配方另存實際執行檔案的 SHA-256。

| 探測設定 | 更新序列長度 | 含恢復重放的秒數 | peak allocated | peak reserved | 下一次更新完全一致 |
| --- | --- | ---: | ---: | ---: | --- |
| 64 tokens | 32、32、32、80 | 96.25 | 2.403 GiB | 4.311 GiB | 是 |
| 96 tokens | 32、32、32、80 | 99.50 | 2.470 GiB | 3.803 GiB | 是 |

每組在第三次更新後保存 checkpoint，再核對恢復後第四次更新的 loss、資料順序與所有權重。PyTorch allocated／reserved 僅表示本行程，不能作為整卡或閉迴路資源驗收。

測速後固定各四次對照更新，兩組重新初始化，共用 seed 2202、資料順序、masking、loss 與凍結標註。64-token 更新耗時 64.19 秒，96-token 為 58.84 秒。兩組均完成固定 200 圖，17 個 task 的圖片配額皆足夠。

| 對照 | 全圖 MSE | LPIPS | UI MSE | 已判讀／全部關鍵項目 | 正確／全部關鍵項目 | Gate |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 64 tokens | 0.079140 | 0.922425 | 0.120983 | 15／15 | 0／15 | failed |
| 96 tokens | 0.079026 | 0.958881 | 0.119646 | 15／15 | 0／15 | failed |

2026-09-25，Jay 在本次對話對照七組原圖／重建圖，分別完成兩個候選的 15 個凍結關鍵項目。全部回覆為無法辨識，兩組各為 0% 正確、0 項缺判、0 項排除；游標 0／2、配方 0／1、物品與數字 0／10、連接 0／2，均未達門檻。各組的 `reviewed-gate.json` 由 `score` 命令產生，保存於對應的 `reconstruction-64`／`reconstruction-96` 目錄；原先的 `gate.json`、metrics、判讀模板與 verification 報告保持原封存內容。

UI 來自八個預標區域的聯集，分布在五張圖，共 568,351 pixels；先逐圖平均再對圖等權平均。全部 800 個原圖／重建 PNG、兩個對照 checkpoint 的檔案 hash，以及報告的封存身分均另行比對通過。這些畫面仍未學出場景細節，四次更新不能支持收斂或容量優劣結論。

成功的完整命令耗時 2,250.34 秒，包含全量來源讀回、探測、恢復、對照、存檔與評估。時數紀錄另保留一輪來源核對中斷的 54.89 秒，合計約 38.42 分鐘，未超過第一階段 A 四小時上限。

CPU 整合檢查已驗證原生解析度與因果性、真實 compiler／loader 至完整 LPIPS loss 的更新、checkpoint 恢復後下一次更新完全一致，以及缺判／缺類型／辨識門檻的 gate 行為。CPU 使用小寬度只供回歸，不能替代 GPU 正式架構驗證。

完整 `pytest -q` 為 161 passed，耗時 185.30 秒。`mypy dsp_dreamer tools/train-tokenizer.py` 的 22 檔通過。兩則警告來自 LPIPS 0.1.4 仍使用 torchvision 的舊 pretrained 參數，實際權重身分已固定，沒有更換 metric。

其後補強歷史影格會影響後續輸出，以及 Python／NumPy／PyTorch RNG 恢復的檢查，單檔三項再次通過。

## Standards

獨立審查原有三項證據追溯問題，均已修正並複核：訓練與評分共用 catalog 固定 ID／checksum 核對；gate 保存封存後的完整人工判讀內容；對照報告不再修改已封存的 run。無剩餘 finding。

## Spec

獨立審查的正式 64-token 限制、第一階段 A 共用四小時預算及 OOM 後才能改 1/16 均已修正並複核。後續發現的截止時間處理亦已修正，恢復重放與定期 validation 逾時仍保留已完成更新的 checkpoint 和 run。無剩餘 finding。

## 驗收界線

凍結 validation 名單、15 個關鍵項目及八個 UI 區域沿用原資料，沒有改動抽樣或標註。人工依事前準則完成判讀後，兩個四次更新候選的重建 gate 均為 failed；此結果不支持收斂後品質或容量優劣的結論。沒有啟動 dynamics 或揭露 offline-test 模型結果。

使用方式、安裝與可重跑指令見 [tokenizer 文件](tokenizer.md)。
