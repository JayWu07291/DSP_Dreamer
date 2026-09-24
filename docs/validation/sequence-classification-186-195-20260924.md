# P186–P195 分類收件

Jay 的十段原文與分類已保存，題號、原文與空白保留，冒號後各三個空白，行分隔統一為 LF，見 [收件收據](sequence-classification-186-195-received-20260924.json)。本批無待補分類，前批 P085 仍待判定。

| 題目 | 分類 | 保留的操作說明 |
| --- | --- | --- |
| P186 | movement | 移動 |
| P187 | interaction | 規劃風力渦輪機 |
| P188 | interaction | 第 5 步仍在調整傳送帶路線，末段才開製造介面 |
| P189 | movement | 移動、縮放視角 |
| P190 | waiting | 查看製造台的製造狀況 |
| P191 | interaction | 前 0.5 秒完成研究站規劃，後段才移到分揀器選單 |
| P192 | interaction | 快捷鍵取熔爐與採礦機物品，末段才開製造介面 |
| P193 | waiting | 等待正在進行的登陸艙拆除 |
| P194 | ui | 設定磁線圈製作數量後按製造鈕 |
| P195 | ui | 從背包把燃料放入機甲介面，再關閉兩個介面 |

已核對 P188、P191、P192 的起點、第 5 步及第 15 步原圖。P188 第 5 步仍在場景中調整傳送帶路線，末段才打開製造介面，歸 interaction。P191 起點研究站仍為放置預覽，第 5 步變成綠色規劃投影並退出放置，末段才移到分揀器選單，歸 interaction，不把完成規劃等同建造完成。

P192 起點游標在熔爐，第 5 步移到採礦機且已有新增銅塊取得提示，末段才開製造介面，結合使用者描述歸 interaction。三段均保留後續介面操作。本批映射依使用者原描述及影像證據，沒有新增使用者未提供的確認。

本批為 movement 2、ui 2、interaction 4、waiting 2。累計收到 195 段描述，完成 194 段分類：movement 12、ui 63、interaction 59、waiting 60。累計待判定仍為 P085，其原回答及草稿未更改。本批十列 `classification_reviewed=true`，但 `regions`／`key_states` 仍為 null、完整候選 `reviewed=false`，完整候選數仍為 0。UI、interaction、waiting 候選數已達 50，movement 仍不足。分類計數不是正式四類各 50 段的入選名單，範圍與關鍵狀態仍待完成，訓練未授權。

本批草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-186-195-received-draft.json`。保存時間是收件時間，沒有冒充逐題作答時間。收據鏈接前批，累計沿用 P085 待判定狀態。

## 下一步

P196–P205 已準備在 <http://127.0.0.1:8854/>，可分次描述操作，不必重新錄製。總分類數接近 200，仍須滿足四類各 50 段，不能以總數到 200 當作分類完成。

沿用 `prepare-sequence-classification.py --start 196 --count 10`，題包 ID 為 `e255757912040d7a4ac24e3be4e8d960c4aa43515b84093272cb4480e8062505`，見 [準備收據](sequence-classification-196-205-prepared.json)。原圖與影片採 hard link，沒有重編碼、複製媒體、開啟歷史 dataset 或重建索引。

## 核對

本批 seal、checksum、題號、來源與計數已核對。195 段描述分成 194 段已分類與 P085 待判定，原文與前批資料未覆寫。下一組連續 ID、來源、時間、hard link、十部播放器及三十張原圖通過既有腳本檢查。本次沒有修改應用程式。

瀏覽器實際播放 P196 的 1.5 秒片段後已自動暫停，影片為 640×360，沒有媒體錯誤。沿用現有分頁切換至下一組。

## Standards

獨立審查未發現硬性違規或可行動的 Fowler smell。收據 seal、前批鏈接、題號、來源與計數一致，P085 仍待判定。十題原文與各三個前導空白均保留，下一組媒體實際採 hard link。

## Spec

獨立審查未發現缺漏、範圍擴張或錯誤分類。P188 的傳送帶規劃、P191 的研究站規劃投影及 P192 的取物提示均依第 5 步映射，保留後續介面操作。總數 200 不等於四類各 50 段已完成。本批十列已分類，完整候選仍為 0，訓練未授權。

Standards 0 項、Spec 0 項發現。
