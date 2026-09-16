# B 建築模式支援與第二批錄製驗證

2026-09-16，使用者確認 B 切換建築模式、X 切換拆除模式。第二批兩回合的遊戲結果都是成功，舊編譯器卻因未支援 B 而判為 invalid。已補上 B，從原始錄製證據重編為 `action_catalog_v4`，兩回合均為 success／valid，不需要重錄。

## 控制與協定

B 追加為 index 20、scan code 0x30。既有 0–19 維保持不變，X 仍為 index 13。Python 模型動作、C# 原生注入、全部按鍵釋放及校正探針同步使用 21 維。舊 dataset、checkpoint 與校正不直接套用新格式，原始 v2／v3 evidence 可另存重編。決議見 [ADR-0002](../adr/0002-build-mode-control.md)。

[evaluation-v2](../../protocols/evaluation-v2.md) 與 [封存 JSON](../../protocols/evaluation-v2.json) 納入新控制契約。舊 v1 及全部綁定檔案保持原樣；門檻、抽樣 seeds、資料切分及 40 個保留試驗不變。v1 重現須使用當時程式版本，例如 `5c13232`，目前工具須明確傳入 `--protocol protocols/evaluation-v2.json`。

## 第二批結果

來源是 `runs/live/2a7d5513-4799-4c09-8146-97faf0777d17.source.evidence`，新版資料是 `runs/catalog-v4/second-batch.dataset`。

| 回合 | 時長 | 舊有效性 | 新有效性 |
| --- | --- | --- | --- |
| 181f1425-1b86-4e5f-827f-c9f897cd14e9 | 361.75 秒 | invalid：unknown_control | valid，成功 |
| 1add132d-6fbc-43cf-bec6-2445c84db77f | 320.34 秒 | invalid：unknown_control | valid，成功 |

13,636 張 RGB 的 hash、原始事件、時間、微任務、節點完成、reward 與 gap 均與舊資料一致。全部既有 20 維按鍵值也一致；2 次 B 按下現在形成 4 個有效模型動作區間。沒有手動修改回合有效性或刪除失效紀錄，舊資料原樣保留。完整核對位於 `runs/catalog-v4/second-batch-verification.json`。

## 完整語料結果

6 份來源共 111,415 張影像已轉為同一控制版本；5 份舊來源的影像、事件、任務進度與回合判定保持一致。原 progress v3 的錄製仍另產生採礦優先的排程 v4 衍生資料。來源清單與新舊 checksum 保存在 [機器可讀報告](catalog-v4.json)，大型資料位於 `runs/catalog-v4`。

新索引 `4a0322fd6571bf386a311cb4bb82b5cde80a2b975fb623d765fffa54d91161b9` 的有效完整回合為 train 11、validation 1、offline-test 0。Train 有效完整示範約 1.075 小時；鐵礦與銅礦採礦機各有 13 回有效 active 完成紀錄，此計數包含合法前綴，不能等同完整回合數。

評估輸入包為 `runs/catalog-v4/evaluation-inputs.json`，ID `d56038d8f03e88b15c8fdf784100cf567e1c171efe774683730ac8fbab58b795`。Train-only baseline 有 17/17 類統計，準備狀態為 ready。重建候選總數為 200，但逐任務配額仍缺手動冶煉 10、熔爐連接 10、矩陣科技供料 10、電路板產線 2 張。預測四類各 50 段仍待人工分類。資料覆蓋 gate 未通過，這些結果不授權訓練。

## 標註保留

Jay 填寫的 5 題局部物品／數字已保存，無待補回答。4 張來源原圖在新版資料逐像素 hash 相同，映射保存在 `runs/catalog-v4/annotation-source-mapping.json`。原答案、原草稿及其來源 ID 保留，尚未將它們直接套入新版抽樣名單。整圖確認仍為 0，不能把 5 題當作 200 張重建圖或 200 段預測序列驗收完成。

## 自動檢查

新增公開介面的回歸案例先重現 B 造成 invalid，再驗證 v3 evidence 可重編並讓模型讀到 B；X 的 index 13 和 B 的 scan code 亦有核對。完整 pytest 156 項通過，192.99 秒，JUnit 位於 `tmp/catalog-v4-tests.xml`。mypy 20 檔通過，C# Release 建置 0 警告、0 錯誤。部署後另重跑 1 項原生插件控制防護測試，通過。

## 部署與實機指紋

新版 DLL SHA-256 為 `5836e7377cf6ddd15cc8fb3758839f97a8a67721b5fdf520b5a5880faf91447d`，已安裝並讀回核對。舊 DLL、設定與部署收據保存在 `runs/catalog-v4/deployment-20260916-232049`。清除舊指紋及校正核准，其他設定保持不變。

使用者已重啟遊戲並按 F6，新指紋為 `dda0773aa09e441e93120cefbf3e6dd3e5ae887a0760047ba78f8f92465c1dae`。已重驗 11 個安裝檔案 hash、遊戲輸入設定及 Starting Save，僅 recorder DLL 相對舊 runtime 改變。全語料背景工作結束後已核准指紋，核對與設定收據在 `runs/catalog-v4/calibration-20260916T153034`；實際校正尚未執行。

## 尚待完成

現在請在 DSP 可操作畫面再按一次 F6 執行校正，全程不要操作鍵鼠或切換視窗。等校正停止並發布完成後回報；本次應包含 45 個模型動作要求及獨立的 keypad 身分探針，我會核對實際讀回與必要釋放。校正通過前先不按 F8 錄製，第二批兩回合不需重錄。

資料覆蓋、人工標註與模型品質 gate 尚未通過，沒有啟動訓練。原 40 個保留試驗引用的輸入設定 hash 與目前設定仍不同，正式試驗前須處理此既有差異。

## Standards

獨立複核指出 README 未清楚區分 v1 重現所需版本，已修正並複核通過。已封存 v2 文本中一個「旧」字保留原 bytes，屬非語意文字瑕疵，不改寫已被評估包引用的封存身分。無其他待修項目。

## Spec

獨立複核沒有阻擋問題，確認原控制編號、B／X 映射、45 個校正模型要求及 identity probe、舊格式拒絕規則均一致。未知鍵仍保留證據並排除，v1 checksum 與評估門檻未變。
