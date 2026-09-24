# P166–P175 分類收件

Jay 的十段原文與分類已保存，題號、原文與空白保留。P167、P170 冒號後各兩個空白，其餘各三個，P170 行尾一個空白，行分隔統一為 LF，見 [收件收據](sequence-classification-166-175-received-20260924.json)。本批無待補分類，前批 P085 仍待判定。

| 題目 | 分類 | 保留的操作說明 |
| --- | --- | --- |
| P166 | interaction | 規劃鐵礦脈採礦機的位置 |
| P167 | movement | 往銅礦脈走 |
| P168 | interaction | 擺放熔爐 |
| P169 | waiting | 查看採礦機與熔爐的狀況 |
| P170 | interaction | 規劃傳送帶 |
| P171 | interaction | 連接傳送帶到熔爐的分揀器 |
| P172 | waiting | 片段內只有游標移動，保留片段前後的建造與供電問題 |
| P173 | waiting | 第 5 步仍在播放基礎製造研究完成提示 |
| P174 | ui | 第 5 步仍在建築選單選研究站，末段才出現放置預覽 |
| P175 | interaction | 規劃製造台到研究站的分揀器 |

已核對 P169、P173、P174 的起點、第 5 步及第 15 步原圖。P169 第 5 步游標仍在採礦機上，既有熔爐面板仍開著，之後才移到熔爐查看，結合使用者描述歸 waiting。P172 使用者明確指出分揀器放置在片段前、電力感應塔選擇與建造在片段後，片段內只有游標移動，因此歸 waiting，不把游標移動當作角色或鏡頭移動。

P173 第 5 步仍是自動解鎖動畫，末段確認按鈕才清楚顯示，歸 waiting，保留之後關閉提示的描述。P174 第 5 步仍在建築選單，末段才出現研究站場景放置預覽，歸 ui，不推定已建造完成。本批映射依使用者原描述及影像證據，沒有新增使用者未提供的確認。

本批為 movement 1、ui 1、interaction 5、waiting 3。累計收到 175 段描述，完成 174 段分類：movement 9、ui 59、interaction 53、waiting 53。累計待判定仍為 P085，其原回答及草稿未更改。本批十列 `classification_reviewed=true`，但 `regions`／`key_states` 仍為 null、完整候選 `reviewed=false`，完整候選數仍為 0。UI、interaction、waiting 候選數已達 50，movement 仍不足。分類計數不是正式四類各 50 段的入選名單，範圍與關鍵狀態仍待完成，訓練未授權。

本批草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-166-175-received-draft.json`。保存時間是收件時間，沒有冒充逐題作答時間。收據鏈接前批，累計沿用 P085 待判定狀態。

## 下一步

P176–P185 已準備在 <http://127.0.0.1:8852/>，可分次描述操作，不必重新錄製。

沿用 `prepare-sequence-classification.py --start 176 --count 10`，題包 ID 為 `f63c6230a4ca2d8d37f48ffa0519d52c84fec1957a1375f498b918f36dcc1ad7`，見 [準備收據](sequence-classification-176-185-prepared.json)。原圖與影片採 hard link，沒有重編碼、複製媒體、開啟歷史 dataset 或重建索引。

## 核對

本批 seal、checksum、題號、來源與計數已核對。175 段描述分成 174 段已分類與 P085 待判定，原文與前批資料未覆寫。下一組連續 ID、來源、時間、hard link、十部播放器及三十張原圖通過既有腳本檢查。本次沒有修改應用程式。

瀏覽器實際播放 P176 的 1.5 秒片段後已自動暫停，影片為 640×360，沒有媒體錯誤。沿用現有分頁切換至下一組。

## Standards

獨立審查未發現硬性違規或可行動的 Fowler smell。收據 seal、前批鏈接、題號、來源與計數一致，P085 仍待判定。P167、P170 的兩個前導空白、其餘三個及 P170 行尾空白均保留，下一組媒體實際採 hard link。

## Spec

獨立審查未發現缺漏、範圍擴張或錯誤分類。P169 查看既有面板、P172 只有游標移動、P173 自動解鎖動畫及 P174 建築選單，均依第 5 步主要可見狀態分類。保留片段前後文，沒有把後續操作推定為已發生。本批十列已分類，完整候選仍為 0，訓練未授權。

Standards 0 項、Spec 0 項發現。
