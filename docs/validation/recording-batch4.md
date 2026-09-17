# 第四批錄製核對

2026-09-17，使用者提交三次嘗試：第二回合誤按開啟星圖的 V，以 F9 重載後完成第三回合。維持 `action_catalog_v4` 的 21 維控制及既有校正，沿用未知控制與重載的有效性規則。

來源為 `runs/live/33f51ab7-0a3d-4c9a-9ea2-6d3a4f0c9e93.source.evidence`，正式資料集位於相鄰 `.source.dataset`，artifact 為 `86be56ef-7fc4-416b-87da-a61f70bb74d0`。共 14,515 張影像、14,514 個轉移，原始三個檔案的 checksum 與正式 Dataset／ModelView 讀回均通過。

| 回合 | 時長 | 遊戲結果 | 資料判定 | 有效轉移 |
| --- | --- | --- | --- | --- |
| 第一回合 | 5 分 51 秒 | 成功 | valid，完整回合可用 | 7,016 |
| 第二回合 | 46 秒 | 尚未結束即重載，outcome 為 null | invalid：reset、unknown_control，保留合法前綴 | 470 |
| 第三回合 | 5 分 29 秒 | 成功 | valid，完整回合可用 | 6,574 |

第二回合第一個未知控制區間在 23.6539165 秒，原始 input sequence 41144 明確記錄 V 按下。該區間及之後資料依既有契約排除。F9 於 45.8270318 秒終止此回合，第三回合使用新的 episode_id／attempt_id；第二回合的失效沒有延伸到第三回合。三次嘗試及原始輸入全部保留，不能將中斷回合算成遊戲失敗或完整有效回合。

三回均屬 demonstration plan index 3，manifest `7c431719b953aa47a0398e3f70e8784c4cbf22c0fe46994fd67b4fa0881d7cb9`、bucket 66、train split。重試沒有更換 manifest 或切分。錄製使用已核准指紋與校正、progress version 4、human 模式，Diagnostics 關閉。

## 索引結果

八份來源共 139,364 張影像完成核對。新索引 ID 為 `d42a1a6ee8e3443ab5db52a88d1f1506798055f0b87ef26163770fbebca6405a`，完整有效回合為 train 14、validation 1、offline-test 0。Train 比上批增加 2 回，完整有效示範約 1.355 小時。

第一回合提供 task 1–13 及 15 的合法 active 正例；第二回合的有效前綴提供 task 1、2；第三回合提供 task 1–10、13、15。鐵、銅採礦機各增加 2 回正例，熔爐連接與矩陣科技供料各增加 1 回。啟動拆解與電路板產線本批沒有新增合法 active 正例，背景完成不補入此計數。逐任務累計與缺口見 [機器可讀核對報告](recording-batch4.json)。

評估輸入包 ID 為 `ff6415d8b299ab5486d7dd474c75e034d26ad7f0584e031dcfa0ce9a85cfa090`。Validation 重建抽樣名單未變，既有人工草稿保留；逐任務圖片配額仍缺 32 張，預測四類各 50 段的分類與完整標註仍待人工處理。Train-only baseline 為 ready，資料覆蓋 gate 仍為 false，未啟動訓練。索引、輸入包、來源 checksum 及核對收據保存在 `runs/catalog-v4/recording-review-20260917-batch4`。

## 後續操作

第四批已有兩個完整有效回合，不需再補錄。第五批按既有登錄順序套用 index 4，seeds 為 230012／230013／230014，manifest `7eb4006cda9692896ebd498712814c3a75e237fdbfce9c40980f70ca25df889b`，固定 bucket 93 屬於 offline-test。此分組由原定 manifest 決定，沒有跳號或重抽。第五批收件時只做契約與標籤覆蓋核對；模型分數仍遵守凍結前不揭露規則。

設定已備份、套用並讀回核對，只修改三個 seeds。存檔、輸入設定、保留 trial 隔離與既有校正均已核對；動作空間、DLL、指紋與 Diagnostics 設定保持不變，不需重啟或再按 F6。

下一步請錄製第五批兩回合：F8 開始，第一回合成功後 F9 重載，第二回合成功後 F8 結束並等待發布完成。維持採礦優先安排。若中途誤觸不支援的按鍵，可像這次一樣用 F9 重載並補一回，原始失效紀錄仍會保留。

本輪未修改產品程式或凍結協定。驗證包含新來源檔案 checksum、八份正式 Dataset／ModelView、TrainingIndex、評估輸入封存與設定讀回；沒有用重跑單元測試取代實際錄製檢查。人工標註、資料覆蓋與模型評估仍未完成。
