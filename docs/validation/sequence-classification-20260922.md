# 首組影片分類收件

2026-09-23 更新：P006–P015 的十段描述已收件，原七個不確定分類也已由 Jay 澄清確認，見 [第二組分類澄清及下一組](sequence-classification-clarification-20260923.md)。

Jay 的五個回答已完整保存，沒有待補的分類題。原文、來源、保存時間及草稿 checksum 見 [收件收據](sequence-classification-01-received-20260922.json)。保存時間是收件時間，沒有冒充逐題作答時間。

| 題目 | 分類 | 使用者原文 |
| --- | --- | --- |
| P001 | waiting | 等待拆除登陸艙(正在拆) |
| P002 | ui | UI，那1.5秒內是選完磁線圈的配方後要開始製作 |
| P003 | ui | UI，打開機甲介面放燃料 |
| P004 | interaction | 建造／物品，去採銅礦脈 |
| P005 | ui | UI，關閉合成介面 |

P001 保留等待分類及正在拆除的補充，沒有把它改寫為畫面靜止或 no-op。累計分類為 movement 0、ui 3、interaction 1、waiting 1。這五筆的 `classification_reviewed=true`，但 `regions`／`key_states` 尚未確認，完整候選 `reviewed=false`，完成候選數仍為 0。分類原文不能直接代替第 15 步的可見關鍵狀態。

原始回答位於 `runs/annotation-submissions/20260922-sequence-classification-01-answers.json`；對應草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-01-received-draft.json`。每筆保留原題包來源、人工回答與確認 ID。

## 第二組的操作說明（已收件）

開啟 <http://127.0.0.1:8835/>，查看 P006–P015。沿用移動／視角、UI、建造／物品、等待四類，回覆「P006：類別＋簡短說明」至「P015：類別＋簡短說明」。可分次回答；不確定可附原因，不用填座標、匯出 JSON 或重新錄製。

這組直接接續固定佇列，沒有按畫面內容或模型結果挑選。題包 ID 為 `372d124ca93842df4f20401daef0da5ff6cdb2aaecfecb8130e97f3151feb3e2`。來源與輸出見 [準備收據](sequence-classification-006-015-prepared.json)，生成命令為 `.venv/Scripts/python.exe docs/validation/prepare-sequence-classification.py --start 6 --count 10`。

## 核對

本次驗證首組題包全部檔案 checksum、保存原文與分類計數；範圍及關鍵狀態保留 null。下一組核對固定佇列 ID、時間、30 張原圖與 3 部影片 checksum；媒體以 hard link 沿用既有儲存，複製量為 0。頁面重用第一組已驗證的樣式、類別說明與播放程式，不重編影片。

準備腳本內建的範圍、連續 ID、路徑、checksum、hard link 及卡片數量檢查通過，mypy 通過；瀏覽器核對題號、說明、播放器定位與停止。本次沒有修改應用程式、開啟歷史 dataset 或重建總索引。正式候選、資料凍結與模型品質仍待完成，訓練未授權。

## Standards

獨立複核沒有硬性違規。有兩項低優先判斷：`root`／`work` 名稱較泛，以及 CLI 在模組載入時執行。此腳本只以命令執行，尚無匯入介面需求；保留現狀。來源驗證與拒絕覆寫檢查均已保留。

## Spec

獨立複核無可操作發現。五個分類保留原文及原始來源；新十段沿固定佇列，包含 6.4 秒前情與涵蓋第 15 步的 1.55 秒區間。分類沒有提前算成完整候選或訓練授權。
