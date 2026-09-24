# B 建築模式支援與第二批錄製驗證

2026-09-21 最新狀態：第十八批三回合均為 success／valid，16 項微任務各取得 3 回合法 active 正例，三個 split 的累加配額全部補齊。指紋與音量設定已恢復核准版本，不需重新校正，詳見 [第十八批錄製核對](recording-batch18.md)。目前不安排第十九批。

2026-09-16，使用者確認 B 切換建築模式、X 切換拆除模式。第二批兩回合的遊戲結果都是成功，舊編譯器卻因未支援 B 而判為 invalid。已補上 B，從原始錄製證據重編為 `action_catalog_v4`，兩回合均為 success／valid，不需要重錄。

2026-09-17 更新：新版實機校正已通過並套用，第三批補錄設定已備妥。新證據見 [校正核對與套用收據](catalog-v4-calibration.json)；原 [轉換報告](catalog-v4.json) 保留當時尚待校正的歷史狀態。

第十八批收件後，完整有效回合合計 train 38、validation 4、offline-test 5，共 47 回。24 份唯一來源已完成一次總索引整合，三個 split 的任務覆蓋 gate 全部通過，且與累加報表一致。200 張 validation 原圖的逐任務配額均滿足，另已匯出 400 段影片候選。最新索引與人工操作見 [語料整合與正式標註準備](corpus-integration-20260921.md)；第五批快照及歷史單批報告保留原樣。

第八批缺口原因見 [任務正例缺口診斷](coverage-diagnosis-batch8.md)。第十八批依原順序使用 offline-test 組，沒有挑選 seeds 或重分 split。最後三回的拆解、熔爐自動接線及矩陣科技供料正例均通過。

第六批起日常收件只驗證新錄製並保存單批索引，引用舊批次報告。第十八批配額完成後才進行一次全語料重建，24 份來源均已納入新總索引。標註使用本次匯出的素材，不因每批填答而重讀全部歷史影像。

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

Jay 先前填寫的 5 題局部物品／數字已保存，無待補回答。4 張來源原圖在新版資料逐像素 hash 相同，映射保存在 `runs/catalog-v4/annotation-source-mapping.json`。這 4 張未被新的固定重建抽樣選中，因此未移植成新名單的答案；原答案、草稿與來源 ID 均保留。新名單已收到 15 個關鍵項目及 8 個 UI 框，涵蓋協定要求的四種關鍵項目與五類 UI。協定沒有要求逐張確認 200 張圖的所有細節，工作台的整圖確認數不另作門檻；完整資料凍結與預測序列標註仍待完成。見 [UI 覆蓋與影片分類](ui-coverage-and-sequence-classification-20260921.md)。

## 自動檢查

新增公開介面的回歸案例先重現 B 造成 invalid，再驗證 v3 evidence 可重編並讓模型讀到 B；X 的 index 13 和 B 的 scan code 亦有核對。完整 pytest 156 項通過，192.99 秒，JUnit 位於 `tmp/catalog-v4-tests.xml`。mypy 20 檔通過，C# Release 建置 0 警告、0 錯誤。部署後另重跑 1 項原生插件控制防護測試，通過。

## 部署與實機指紋

新版 DLL SHA-256 為 `5836e7377cf6ddd15cc8fb3758839f97a8a67721b5fdf520b5a5880faf91447d`，已安裝並讀回核對。舊 DLL、設定與部署收據保存在 `runs/catalog-v4/deployment-20260916-232049`。清除舊指紋及校正核准，其他設定保持不變。

使用者已重啟遊戲並按 F6，新指紋為 `dda0773aa09e441e93120cefbf3e6dd3e5ae887a0760047ba78f8f92465c1dae`。已重驗 11 個安裝檔案 hash、遊戲輸入設定及 Starting Save，僅 recorder DLL 相對舊 runtime 改變。全語料背景工作結束後已核准指紋，核對與設定收據在 `runs/catalog-v4/calibration-20260916T153034`。

實際校正錄製為 `6cd4ec98-b96d-4824-9a86-7728d19ab5bb`，415 張影像、414 個轉移。已重新驗證原始 evidence 與正式 dataset，45/45 個模型控制要求、46/46 次必要釋放及 keypad 身分探針均通過。輸入延遲 10.4174–18.4793 ms；B 的實際讀回為 17.1466 ms，X 為 15.1885 ms。完整鍵盤、滑鼠 bins、滾輪與固定 20.0 倍率通過既有 `publish_calibration` 檢查。校正錄製維持 diagnostic，未加入訓練索引。

校正檔 SHA-256 為 `7115daf206e5fb637a5e4e0cc27265752194214c1566847e5aaf6cee71d50dbc`，已寫入設定並讀回核對。原設定已備份。第三批按既有 demonstration plan 的 index 2 使用 seeds 230006／230007／230008，manifest `a980b35ca42b710f969c8d4f203e38b6c04df4f0b5f1adb9955c6e4f92b78c51`，固定 bucket 19 屬於 train。已核對 registry、40 個保留 trial 隔離、存檔與輸入設定，沒有跳號挑 split。Diagnostics 保持關閉，既有語料索引未變。

## 尚待完成

第十八批、總整合及兩組共 15 題局部標註已完成，不需繼續錄製。Q05 已由使用者補充確認，左、右兩座熔爐均未建造完成；兩組共 8 個 UI 框也已確認。P001–P155 的描述已保存，其中 154 段完成分類，P085 的取物時間不確定、分類待判定；累計移動 8、UI 52、建造／物品 46、等待 48。下一組 P156–P165 已準備在 `http://127.0.0.1:8850/`。範圍與關鍵狀態仍待確認，見 [第十六批分類收件](sequence-classification-146-155-20260924.md)。

資料覆蓋 gate 已通過；人工標註、資料凍結與模型品質 gate 尚未完成，沒有啟動訓練。原 40 個保留試驗引用的輸入設定 hash 與目前設定仍不同，正式試驗前須處理此既有差異。

## Standards

獨立複核指出 README 未清楚區分 v1 重現所需版本，已修正並複核通過。已封存 v2 文本中一個「旧」字保留原 bytes，屬非語意文字瑕疵，不改寫已被評估包引用的封存身分。無其他待修項目。

## Spec

獨立複核沒有阻擋問題，確認原控制編號、B／X 映射、45 個校正模型要求及 identity probe、舊格式拒絕規則均一致。未知鍵仍保留證據並排除，v1 checksum 與評估門檻未變。
