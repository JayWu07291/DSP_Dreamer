# P116–P125 分類收件

Jay 的十段原文與分類已保存，題號、原文與空白保留，P118–P125 冒號後各三個空白，行分隔統一為 LF，見 [收件收據](sequence-classification-116-125-received-20260924.json)。本批無待補分類，前批 P085 仍待判定。

| 題目 | 分類 | 保留的操作說明 |
| --- | --- | --- |
| P116 | interaction | 點銅礦脈並走近，第 5 步已開始採礦，保留取得第一個銅礦的描述 |
| P117 | interaction | 用快捷鍵拿取兩個採礦機中的礦物 |
| P118 | interaction | 正在擺放鐵礦採礦機 |
| P119 | waiting | 等待 |
| P120 | interaction | 正在擺放熔爐 |
| P121 | interaction | 用快捷鍵取鐵礦，再將礦物放入熔爐 |
| P122 | waiting | 等待 |
| P123 | ui | 第 5 步仍從選單選風力渦輪機，後段準備放置 |
| P124 | waiting | 佇列已排好，第 5 步仍在製作，後段才關閉介面 |
| P125 | waiting | 查看製造台的製作狀況 |

已核對 P116、P123、P124 的起點、第 5 步及第 15 步原圖。P116 第 5 步已到達銅礦脈並開始採礦，歸 interaction；點礦、移動及取得第一個銅礦的原描述均保留。P123 第 5 步游標仍在下方建造選單、尚無場景放置預覽，歸 ui，後段才進入放置狀態，不推定已放置或供電。

P124 起點的製作佇列已排好，第 5 步面板仍開著、游標位置未變，既有佇列繼續製作，末段才關面板。依第 5 步歸 waiting，保留後段關閉介面。此分類來自原描述與原圖映射，沒有額外人工澄清。P119、P122 不補寫等待原因；P118、P120 不推定已建造完成。

本批為 movement 0、ui 1、interaction 5、waiting 4。累計收到 125 段描述，完成 124 段分類：movement 5、ui 41、interaction 37、waiting 41。累計待判定仍為 P085，其原回答及草稿未更改。本批十列 `classification_reviewed=true`，但 `regions`／`key_states` 仍為 null、完整候選 `reviewed=false`，完整候選數仍為 0。分類計數不是正式四類各 50 段的入選名單，資料與模型品質 gate 待完成，訓練未授權。

本批草稿為 `runs/catalog-v4/corpus-integration-20260921/sequence-classification-116-125-received-draft.json`。保存時間是收件時間，沒有冒充逐題作答時間。收據鏈接前批澄清後收據，累計沿用 P085 待判定狀態。

## 下一步

P126–P135 已準備在 <http://127.0.0.1:8847/>，可分次描述操作，不必重新錄製。

沿用 `prepare-sequence-classification.py --start 126 --count 10`，題包 ID 為 `5808a7e091a9a10d5482d72e7cd1f41fe8b3a1670aef4d4872c482ee07d17dd7`，見 [準備收據](sequence-classification-126-135-prepared.json)。原圖與影片採 hard link，沒有重編碼、複製媒體、開啟歷史 dataset 或重建索引。

## 核對

本批 seal、checksum、題號、來源與計數已核對。125 段描述分成 124 段已分類與 P085 待判定，原文與前批資料未覆寫。下一組連續 ID、來源、時間、hard link、十部播放器及三十張原圖通過既有腳本檢查。本次沒有修改應用程式。

瀏覽器實際播放 P126 的 1.5 秒片段後已自動暫停，影片為 640×360，沒有媒體錯誤。

## Standards

獨立審查未發現硬性違規或可行動的 Fowler smell。收據 seal、前批鏈接、原文空白、來源與計數一致，P085 仍待判定。P124 明確記錄為原描述與影像映射，沒有寫成額外人工確認；下一組媒體實際採 hard link。

## Spec

獨立審查未發現缺漏、範圍擴張或錯誤分類。P116、P123、P124 依第 5 步主要可見狀態分類；P124 既有佇列持續製作，關閉面板發生於後段，歸 waiting 合理。本批十列已分類，完整候選仍為 0，訓練未授權。

Standards 0 項、Spec 0 項發現。
