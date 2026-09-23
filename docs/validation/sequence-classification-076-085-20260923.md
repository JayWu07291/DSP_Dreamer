# P076–P085 分類收件

Jay 的十段原文已保存，題號、原文與尾端空白保留，行分隔統一為 LF，見 [初次收件](sequence-classification-076-085-received-20260923.json)。九段分類已完成；P085 對第 5 步取礦時間回答「不確定」，保留待判定，見 [補充回答收據](sequence-076-085-clarified-20260923.json)。

| 題目 | 分類 | 保留的操作說明 |
| --- | --- | --- |
| P076 | interaction | 放置風力渦輪機，最後才打開製造介面 |
| P077 | interaction | 規劃分揀器 |
| P078 | interaction | 規劃分揀器 |
| P079 | interaction | 建造研究站 |
| P080 | movement | 移動 |
| P081 | waiting | 等待正在進行的登陸艙拆除 |
| P082 | ui | 製作磁線圈，再選電路板並設定製作數量 |
| P083 | ui | 打開機甲介面放燃料，然後關閉 |
| P084 | interaction | 挖銅塊脈，保留原用詞 |
| P085 | 待判定 | 關閉製作介面後取兩台採礦機的礦物，第 5 步是否已開始取物不確定 |

已核對 P076、P085 的起點、第 5 步及第 15 步原圖。P076 第 5 步仍在場景中放置風力渦輪機，末段才開啟製造介面，依既定規則歸 interaction；不推定建造完成或已供電。P077、P078 的規劃也不等同建造完成或連接成功。

P085 起點製作介面開著，第 5 步已關閉、游標懸停鐵礦採礦機，末段才見取得鐵礦提示。Jay 不確定當時是否已按快捷鍵，故不把懸停或延後提示推定成確定的取物時間，也不將不確定回答當成已確認 UI。原文的先關介面、後取礦順序保留。

本批為 movement 1、ui 2、interaction 5、waiting 1，P085 待判定。累計收到 85 段描述，完成 84 段分類：movement 2、ui 28、interaction 25、waiting 29。九列 `classification_reviewed=true`；P085 的 `category=null`、`classification_reviewed=false`。全部 `regions`／`key_states` 仍為 null、完整候選 `reviewed=false`，完整候選數仍為 0。分類計數不是正式四類各 50 段的入選名單，資料與模型品質 gate 待完成，訓練未授權。

最新草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-076-085-clarified-draft.json`。初次收件與補充回答分別保存，不覆寫原文與來源；保存時間為收件時間，沒有冒充逐題作答時間。後續累計須沿用本批 84 段與 P085 待判定狀態，不可默認前批全部已分類。

## 下一步

P086–P095 已準備在 <http://127.0.0.1:8843/>，可分次描述操作，不必重新錄製。P085 暫留待判定，不妨礙接著描述下一組。

沿用 `prepare-sequence-classification.py --start 86 --count 10`，題包 ID 為 `4f644c1ba30598a30bc044443790d6688363977d7131a4c6e21b667a2ab1edc1`，見 [準備收據](sequence-classification-086-095-prepared.json)。原圖與影片採 hard link，沒有重編碼、複製媒體、開啟歷史 dataset 或重建索引。

## 核對

本批 seal、checksum、題號、來源與計數已核對。補充回答只更新 P085 的分類依據與澄清鏈接，分類維持待判定；其餘九列、全部原文及來源不變。下一組連續 ID、來源、時間、hard link、十部播放器及三十張原圖通過既有腳本檢查。本次沒有修改應用程式。

瀏覽器實際播放 P086 的 1.5 秒片段後已自動暫停，影片為 640×360，沒有媒體錯誤。

## Standards

獨立審查未發現硬性違規或可行動的 Fowler smell。收據 seal、鏈接、原文、來源與計數一致；P085 的不確定回答保持待判定。下一組媒體實際採 hard link，沒有複製素材或重建語料。

## Spec

獨立審查未發現缺漏、範圍擴張或錯誤分類。混合片段依第 5 步核對，不把游標懸停推定為取物。九列已分類、P085 待判定，完整候選仍為 0，訓練未授權；下一組仍為固定十題。

Standards 0 項、Spec 0 項發現。
