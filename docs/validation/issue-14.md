# Issue #14 生命週期驗證

狀態：程式與離線整合已實作；同一工作階段的實機重試、科技與工廠事件重綁仍待驗證。既有單回合證據不代表 #14 全部驗收通過。

## 契約與實作

依 [#14](https://github.com/JayWu07291/DSP_Dreamer/issues/14) 與 [#12](https://github.com/JayWu07291/DSP_Dreamer/issues/12)，trial manifest 凍結基準 SHA-256、世界與輸入設定、畫面尺寸及三個 seeds。機甲／相機使用獨立 `System.Random/net472`，各均勻取 ±15 度。F9 重試保留 trial 與 split group，重新產生 attempt／episode ID；來源四檔可容納多個回合。

首個有效 RGB 的 request ticks 決定起點，`world_ready` 僅表示事件重綁完成。單調時鐘的 1,800 秒期限包含 UI 與暫停。success／unrecoverable 由後續任務或控制模組呼叫公開 `EndEpisode`；本票沒有加入任務成功判定，也不以停滯推測失敗。

結束時釋放控制並嘗試取得 final observation；缺失尾端標 `incomplete`。資料集 `/2` 保存 outcome 與 validity、terminal／truncation／bootstrap masks、回合來源與 sequence 起點。舊 `/1` 資料集明確拒絕，保留原 evidence 後重編譯為新 artifact。致命 writer／queue 故障僅盡力保存 `INCOMPLETE.json` 診斷，不將其當作成功來源，也不宣稱可恢復損壞影片。

## 自動化檢查

`tests/test_lifecycle.py` 的 11 個整合案例通過，涵蓋：

- 同 manifest 重試的新身分、跨回合轉移排除。
- success／death／unrecoverable／timeout 與有效性原因分離。
- 回呼逆序且晚於結束時，仍以 request time 判定 final。
- 固定 game tick 的暫停輸入、缺 final 的合法故障前綴與尾端 mask。
- gap 不跨 sequence、未知控制之後同回合範圍排除。
- 舊資料集版本與缺基準 provenance 的 live source 拒絕。

完整 pytest 套件 24 案通過，耗時 30.81 秒（`tmp/issue14-tests.xml`）；mypy 檢查八個原始碼檔案無問題；Release net472 建置零警告、零錯誤。合成案例不證明 Unity 真實暫停 30 分鐘、控制注入故障或磁碟故障行為；這些不得記為實機已測。

## 已有實機證據

使用者指定基準 `Starting Save`，世界種子 `97807908`，基準 SHA-256：
`df9ef534e5dc8e5537f5c1870cd17aacc77259491b770559ef59b4489ab1610f`。

來源：`runs/live/af127c1e-a0d2-4991-bb84-ed2f85cea183.source`。
四檔 evidence 位於同名 `.source.evidence`；2026-09-09 重新完整解碼及 checksum 驗證通過。此錄製使用修正前 DLL `7cfe67c35e43ec6996ce6c81f8385ba362b5bf0676666abd5e7d3a50ee5954b2`，不能替代新修正部署後的驗證。

| 項目 | 實測 |
| --- | --- |
| 錄製幀／事件 | 5,424／25,029 |
| 回合數 | 1 |
| 起點至失焦 | 271.2514982 秒 |
| 起點相對 world_ready | 晚 42.594 毫秒 |
| 機甲／相機偏航 | 3.22420833549658／11.2973214435844 度 |
| 結束原因 | `focus_loss`，outcome 為 null |
| final capture | 5423，尾轉移 invalid、bootstrap 0 |
| release_all 要求 | 6 次皆記錄 succeeded=true；這是注入回傳值，不等於逐鍵實機觀察 |
| 科技／建造／拆除事件 | 全部 0，事件重綁尚無證據 |

以 `/2` 重編譯至 `runs/live/issue14-recompiled-v2` 並完整讀回：5,423 筆轉移、5,416 筆合法轉移、5,164 個合法 64-step 起點。這些仍是 20 Hz 轉移，不是 10 Hz 模型視圖。
新 `dataset.json` SHA-256 為 `aa2c76534cebabeba834de0f0894f2db2300cc1441eb2627788fb2cf430dd4e1`。

## 審查

### Standards

恢復後的獨立審查未發現重要的書面規範違反或需要修正的程式結構問題。資料集版本已升 `/2`。

### Spec

已修正控制釋放拋錯阻斷清理、晚到 callback 誤判 final、未知控制後的範圍、fatal fault 漏記結束、首次重載失敗的清理、錯誤原因混用，以及 live trial 缺必要欄位未拒絕等問題。獨立複查確認最後三項修正通過，未發現仍有重大缺口；實機重綁保持待驗證。

審查收尾：Standards 0 項待修；Spec 已指出問題均修正，實機驗收尚未完成。

## 使用者實機操作

新版部署與指紋核對完成後，再開始以下流程。操作期間不覆寫 `Starting Save`，不要使用沙盒、加速或直接解鎖科技。

2026-09-09 21:25 已部署 Release DLL：`f9ad1bcbac33f19f8518be67ede8a28c22d26d318e8f357ee02d9d8abdd7027f`。既有插件與設定備份在 `runs/deployment-20260909-212525`；新指紋仍待使用者啟動遊戲後核對。

1. 從 Steam 啟動 DSP，載入 `Starting Save`，按一次 F8 產生候選指紋。回報已按 F8，由 agent 核對檔案並設定核准指紋。
2. 核准後按 F8，等待插件自行重載，再正常拆登陸艙、合成 10 磁線圈、研究電磁學、建造一台可用建築，等建造完成後拆除它。
3. 按 F9。等待自動重載，再重做電磁學研究、建造及拆除，以核對新世界事件各只記錄一次。
4. 第二次操作結束後按 F8，等待背景處理完成再退出遊戲，回報「實機重試完成」。agent 會讀取 LogOutput 與新產物，核對 IDs、trial、邊界、事件及 dataset。

本次短流程驗證生命週期及事件重綁；完整 30 分鐘資源／掉幀品質門檻仍須依正式整合驗收另測。
