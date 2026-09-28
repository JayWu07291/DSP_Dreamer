# 允許未通過 A 品質 gate 的 B 探索訓練

2026-09-28，使用者在 A 重構仍有多餘 UI、科技樹模糊的情況下，要求直接嘗試 B。這是訓練實驗，不把尚未通過的 A gate 改為通過。

既有入口只允許已通過 A gate 的正式 B，或只用合成 fixtures 的工程 smoke。新增明確的 `B --exploratory`，允許已凍結的真實資料和未合格 tokenizer。模型、資料身分、action codec、split 和有效片段核對仍須通過。

探索 checkpoint 保存 `formal=False`、`exploratory=True` 和來源身分。預測評估維持非正式資格，不能作為 second、third 或正式 runner 的合格來源。原正式 gate、門檻和 200 段完整評估規則不變。

探索 B 使用 `runs/B-exploratory-budget.json`，與正式入口共用 `training-budget.lock`。它不重設 A 的帳本或消耗正式 B 的額度，實際用量另行保存。可用完成更新數為目標，故障和停機不減少完成目標；恢復仍需最新完整 checkpoint，不能回退帳本。

來源 tokenizer 保持凍結。新增訓練控制程式後，舊 A checkpoint 的全專案指紋必然不同；探索 B 僅接受四個既有模型運算檔案的精確指紋仍相同，並保留來源 checkpoint hash。新 B 自身則保存並核對完整當前實作。這個來源核對例外僅用於探索 B，不放寬正式載入器。

這項決定只允許觀察 dynamics 是否能從目前 latent 學到動作條件預測，不宣稱能修復 A、已符合正式評估條件或能直接訓練策略。
