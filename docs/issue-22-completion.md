# Issue #22 完成核對

2026-09-25 重新讀取 [Issue #22](https://github.com/JayWu07291/DSP_Dreamer/issues/22) 的最新要求，逐條核對協定及 `data/evaluation/` 的凍結交付。**六項驗收條件均已完成，依使用者指示結案。** 前置 Issue #19 已關閉，資料覆蓋 gate 亦已通過。先前依要求暫時保持開啟的狀態已解除。

| 驗收條件 | 證據與結果 |
| --- | --- |
| 固定評分、格式、抽樣、區域、baseline、seed、門檻與版本 | `protocols/evaluation-v2.json` 綁定協定與實作的 checksum；baseline 僅由 train 建立，沒有使用模型結果更改規則。 |
| 重建 200 圖、每 task 至少 10；預測四類各 50，包含三種對照 | 原 200 圖名單未變，17 個 task 均達配額；241 個完整人工候選固定抽出 200 段。15 個關鍵項目、8 個 UI 範圍已確認。no-op、同類打亂與複製末圖的配對、動作差異及 seed 均已保存。 |
| 定義重建、預測、reward、policy 門檻與分母 | 協定明訂所有門檻；零 baseline 誤差、無動作差異、缺類別／正例及未定義 precision 均不能算通過。未測值保持 pending／null。 |
| 固定 10 development、30 final manifests 與隔離 | `protocols/evaluation-trials-v1.json` 固定 40 份試驗；內容、registry、seed、偏航及示範隔離已驗證。兩候選使用同一 development 集，final 不參與選模。 |
| 固定 offline-test 揭露與凍結順序 | 補錄前協定已固定；補錄後來源、split、標註及名單已凍結。揭露仍要求之後的 recipe freeze、checkpoint 與未看 test／final 的聲明。 |
| 暫緩期間不捏造人工結果、不越過 gate | 後續由 Jay 明確恢復並完成人工標註，最後 127 題已確認。P085 的不確定回答仍保留，未列入正式抽樣；未執行模型判讀或授權跨過訓練 gate。 |

資料凍結 ID 為 `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f`，protocol v2 ID 為 `40167e30d83bab5b60b19498ac45380899cd942d8f87fc347db37cae893a9e42`。整理資料夾時必須保留這些 artifact 的原始位元組與身分。

2026-09-24 凍結工具的輕量 `--check` 通過，沒有重讀整批影像。此前完整測試為 158 項通過，mypy 18 檔通過；Standards 與 Spec 獨立複核均無待修問題。

2026-09-25 僅讀取小型 JSON 核對現況，確認重建 200 圖且 17 個 task 各至少 10 圖、預測四類各 50 段、各段具已確認區域與關鍵狀態及對照配對、baseline 僅來自 train、10 development／30 final manifests、凍結檔案的 ID 引用一致。現有 47 個完整有效回合分為 train 38、validation 4、offline-test 5；241 個人工候選中固定選出 200 段。沒有重新抽樣、改寫凍結檔案、重讀錄像或重跑完整測試。

資料夾整理與封存已完成，本機暫存副本已清理；參考論文、反編譯檔案及參考程式碼保留。位置與還原方式見 [資料位置](data-layout.md)及[封存紀錄](archive.md)。

## 後續工作

模型實作、訓練、模型輸出判讀、品質 gate、recipe freeze 及真實遊戲試驗尚未完成，屬本票所定義協定的後續執行。目前沒有模型品質通過或訓練授權。

40 份固定試驗的輸入設定 hash 與目前示範環境不同，須在實際試驗前核對處理；固定 manifests 存在不表示現場已能直接執行。
