# Issue #22 完成核對

2026-09-24 重新讀取 [Issue #22](https://github.com/JayWu07291/DSP_Dreamer/issues/22) 的六項驗收條件，並核對本機 `0f3a9be` 的交付。**本票的協定、評估資料準備與凍結工作已完成。依使用者要求，Issue 保持 OPEN，未修改勾選、標籤或留言。**

| 驗收條件 | 證據與結果 |
| --- | --- |
| 固定評分、格式、抽樣、區域、baseline、seed、門檻與版本 | `protocols/evaluation-v2.json` 綁定協定與實作的 checksum；baseline 僅由 train 建立，沒有使用模型結果更改規則。 |
| 重建 200 圖、每 task 至少 10；預測四類各 50，包含三種對照 | 原 200 圖名單未變，17 個 task 均達配額；241 個完整人工候選固定抽出 200 段。15 個關鍵項目、8 個 UI 範圍已確認。no-op、同類打亂與複製末圖的配對、動作差異及 seed 均已保存。 |
| 定義重建、預測、reward、policy 門檻與分母 | 協定明訂所有門檻；零 baseline 誤差、無動作差異、缺類別／正例及未定義 precision 均不能算通過。未測值保持 pending／null。 |
| 固定 10 development、30 final manifests 與隔離 | `protocols/evaluation-trials-v1.json` 固定 40 份試驗；內容、registry、seed、偏航及示範隔離已驗證。兩候選使用同一 development 集，final 不參與選模。 |
| 固定 offline-test 揭露與凍結順序 | 補錄前協定已固定；補錄後來源、split、標註及名單已凍結。揭露仍要求之後的 recipe freeze、checkpoint 與未看 test／final 的聲明。 |
| 暫緩期間不捏造人工結果、不越過 gate | 後續由 Jay 明確恢復並完成人工標註，最後 127 題已確認。P085 的不確定回答仍保留，未列入正式抽樣；未執行模型判讀或授權跨過訓練 gate。 |

資料凍結 ID 為 `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f`，protocol v2 ID 為 `40167e30d83bab5b60b19498ac45380899cd942d8f87fc347db37cae893a9e42`。整理資料夾時必須保留這些 artifact 的原始位元組與身分。

本次重新執行凍結工具的輕量 `--check` 通過，沒有重讀整批影像。此前完整測試為 158 項通過，mypy 18 檔通過；Standards 與 Spec 獨立複核均無待修問題。

## 後續工作

模型實作、訓練、模型輸出判讀、品質 gate、recipe freeze 及真實遊戲試驗尚未完成，屬本票所定義協定的後續執行。目前沒有模型品質通過或訓練授權。

40 份固定試驗的輸入設定 hash 與目前示範環境不同，須在實際試驗前核對處理；固定 manifests 存在不表示現場已能直接執行。
