# P176–P185 分類收件

後續進度見 [P186–P195 分類收件](sequence-classification-186-195-20260924.md)；本文保留本批收件時狀態。

Jay 的十段原文與分類已保存，題號、原文與空白保留，冒號後各三個空白，行分隔統一為 LF，見 [收件收據](sequence-classification-176-185-received-20260924.json)。本批無待補分類，前批 P085 仍待判定。

| 題目 | 分類 | 保留的操作說明 |
| --- | --- | --- |
| P176 | waiting | 等待物品製作與科技研究 |
| P177 | waiting | 等待正在進行的登陸艙拆除 |
| P178 | ui | 選電路板配方並設定製作數量 |
| P179 | ui | 打開機甲介面、放燃料、關閉介面 |
| P180 | interaction | 正在挖銅礦脈 |
| P181 | movement | 移動視角 |
| P182 | waiting | 觀看無人機建造風力渦輪機 |
| P183 | waiting | 採礦機在起點已建好，之後游標移走 |
| P184 | interaction | 前 0.5 秒完成熔爐放置規劃，轉成綠色投影 |
| P185 | waiting | 等待物品製作與科技研究 |

已核對 P183、P184 的起點、第 5 步及第 15 步原圖。P183 起點採礦機已為實體、沒有放置預覽，第 5 步游標移開而場景位置不變，結合使用者描述歸 waiting，不把游標移動當作角色或鏡頭移動。

P184 起點仍有熔爐藍色放置預覽，第 5 步已變成綠色規劃投影並退出放置狀態，歸 interaction。完成規劃不等同無人機已建造完成，末段開啟熔爐面板也不取代第 5 步分類。P182 是觀看無人機自動施工，歸 waiting。本批映射依使用者原描述及影像證據，沒有新增使用者未提供的確認。

本批為 movement 1、ui 2、interaction 2、waiting 5。累計收到 185 段描述，完成 184 段分類：movement 10、ui 61、interaction 55、waiting 58。累計待判定仍為 P085，其原回答及草稿未更改。本批十列 `classification_reviewed=true`，但 `regions`／`key_states` 仍為 null、完整候選 `reviewed=false`，完整候選數仍為 0。UI、interaction、waiting 候選數已達 50，movement 仍不足。分類計數不是正式四類各 50 段的入選名單，範圍與關鍵狀態仍待完成，訓練未授權。

本批草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-176-185-received-draft.json`。保存時間是收件時間，沒有冒充逐題作答時間。收據鏈接前批，累計沿用 P085 待判定狀態。

## 下一步

P186–P195 已準備在 <http://127.0.0.1:8853/>，可分次描述操作，不必重新錄製。

沿用 `prepare-sequence-classification.py --start 186 --count 10`，題包 ID 為 `6a97be1938424906cefd29a84043d97424f7fe8e7d7eaca9afd0f41a71168a7e`，見 [準備收據](sequence-classification-186-195-prepared.json)。原圖與影片採 hard link，沒有重編碼、複製媒體、開啟歷史 dataset 或重建索引。

## 核對

本批 seal、checksum、題號、來源與計數已核對。185 段描述分成 184 段已分類與 P085 待判定，原文與前批資料未覆寫。下一組連續 ID、來源、時間、hard link、十部播放器及三十張原圖通過既有腳本檢查。本次沒有修改應用程式。

瀏覽器實際播放 P186 的 1.5 秒片段後已自動暫停，影片為 640×360，沒有媒體錯誤。沿用現有分頁切換至下一組。

## Standards

獨立審查未發現硬性違規或可行動的 Fowler smell。收據 seal、前批鏈接、題號、來源與計數一致，P085 仍待判定。十題原文與各三個前導空白均保留，下一組媒體實際採 hard link。

## Spec

獨立審查未發現缺漏、範圍擴張或錯誤分類。P183 的已建成採礦機與游標移動、P184 的藍色預覽轉綠色規劃，以及 P182 的自動施工均有區分，沒有把完成規劃當成建造完成。本批十列已分類，完整候選仍為 0，訓練未授權。

Standards 0 項、Spec 0 項發現。
