# Issue #24 驗證紀錄

本票交付 tokenizer、真實模型視圖訓練、checkpoint 恢復、64／96-token 對照和重建 gate 評分工具。正式 v1 固定 64 tokens；工程驗證不等於模型品質通過。

## 本機驗證

正式 GPU 驗證執行中。結果將由 `runs/issue-24/verification/verification.json` 保存，權重、逐次抽樣、配方、重建 PNG 和人工判讀模板保存在同目錄。大型本機輸出不納入 Git。

CPU 整合檢查已驗證原生解析度與因果性、真實 compiler／loader 至完整 LPIPS loss 的更新、checkpoint 恢復後下一次更新完全一致，以及缺判／缺類型／辨識門檻的 gate 行為。CPU 使用小寬度只供回歸，不能替代 GPU 正式架構驗證。

完整 `pytest -q` 為 161 passed，耗時 185.30 秒。`mypy dsp_dreamer tools/train-tokenizer.py` 的 22 檔通過。兩則警告來自 LPIPS 0.1.4 仍使用 torchvision 的舊 pretrained 參數，實際權重身分已固定，沒有更換 metric。

## Standards

獨立審查原有三項證據追溯問題，均已修正並複核：訓練與評分共用 catalog 固定 ID／checksum 核對；gate 保存封存後的完整人工判讀內容；對照報告不再修改已封存的 run。無剩餘 finding。

## Spec

獨立審查的正式 64-token 限制、第一階段 A 共用四小時預算及 OOM 後才能改 1/16 均已修正並複核。後續發現的截止時間處理亦已修正，恢復重放與定期 validation 逾時仍保留已完成更新的 checkpoint 和 run。無剩餘 finding。

## 驗收界線

凍結 validation 名單、15 個關鍵項目及八個 UI 區域沿用原資料，沒有改動抽樣或標註。重建項目需要人依事前準則判讀；沒有結果的項目保持 null，仍留在分母。尚未宣告重建 gate 通過，也沒有啟動 dynamics 或揭露 offline-test 模型結果。

使用方式、安裝與可重跑指令見 [tokenizer 文件](tokenizer.md)。
