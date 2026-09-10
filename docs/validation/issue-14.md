# Issue #14 生命週期驗證

2026-09-10 最新狀態：實機重試與事件重綁已驗證，新增 30 分鐘自動超時證據（見文末）。人工介入及受控故障的實機控制釋放仍未直接驗證；本報告不宣稱 #14 全部條件或 #21 資源品質 gate 已通過。

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

審查收尾：Standards 0 項待修；Spec 已指出問題均修正，後續實機重綁結果見文末。

## 使用者實機操作

新版部署與指紋核對完成後，再開始以下流程。操作期間不覆寫 `Starting Save`，不要使用沙盒、加速或直接解鎖科技。

2026-09-09 21:25 已部署 Release DLL：`f9ad1bcbac33f19f8518be67ede8a28c22d26d318e8f357ee02d9d8abdd7027f`。既有插件與設定備份在 `runs/deployment-20260909-212525`；新指紋仍待使用者啟動遊戲後核對。

1. 從 Steam 啟動 DSP，載入 `Starting Save`，按一次 F8 產生候選指紋。回報已按 F8，由 agent 核對檔案並設定核准指紋。
2. 核准後按 F8，等待插件自行重載，再正常拆登陸艙、合成 10 磁線圈、研究電磁學、建造一台可用建築，等建造完成後拆除它。
3. 按 F9。等待自動重載，再重做電磁學研究、建造及拆除，以核對新世界事件各只記錄一次。
4. 第二次操作結束後按 F8，等待背景處理完成再退出遊戲，回報「實機重試完成」。agent 會讀取 LogOutput 與新產物，核對 IDs、trial、邊界、事件及 dataset。

本次短流程驗證生命週期及事件重綁；完整 30 分鐘資源／掉幀品質門檻仍須依正式整合驗收另測。

## 2026-09-09：使用者實機重試驗證通過

使用者自行完成兩次電磁學研究、建造及拆除，中間以 F9 重試、最後 F8 停止；此階段沒有使用 Computer Use。候選指紋經九個二進位及輸入設定核對後核准，SHA-256 為 `f0aa3c24fd3b92394c987d9951888a8cd7cbe7ab439b7db154a952c82ce7310a`。

新來源為 `runs/live/d41c9b63-468c-4d52-bc46-069278daa15c.source`，同名 `.source.evidence` 與 `.source.dataset` 已產生。使用 `tmp/verify-issue14-live.py` 呼叫正式 `verify_recording` 與 `open_dataset`，完成影片全幀解碼、RGBA／檔案 checksum、RGB chunks 讀回、來源身分與 sequence 邊界斷言，退出碼 0。

| 項目 | 第一次回合 | F9 重試後 |
| --- | --- | --- |
| attempt_id | `289f18f3-418d-442a-b4e8-0d569c47d835` | `1abcda08-94bb-4860-b33b-2e3214172eb6` |
| episode_id | `97ba2e48-cd1f-4359-b5cb-84d9f1f4bb1c` | `f4d0a5a5-3e6c-4cb5-b21c-592d6a74b893` |
| world_binding | 3 | 4 |
| 幀數 | 1,208 | 1,356 |
| 回合秒數 | 60.438123 | 67.7844409 |
| world_ready 至起點 | 35.3825 ms | 33.9636 ms |
| 科技／建造／拆除事件 | 1／2／2 | 1／2／2 |
| 結束原因 | reset | stopped |
| final capture_id | 1207 | 2563 |

兩回合共享 session `9ff0496d-adef-4ced-9b71-f4b4da944e12`、trial manifest／split group `bec428373a7da8bf99c5a69cb730c84a3e5aa88ea62d693ce857793aa652f824`。基準 hash、三個 seeds 與偏航值均保持原樣。每個世界只有一次 world_ready、擾動、episode_started 與 episode_ended；兩次科技均為 `tech_id=1001`、`direct=false`，建造／拆除的 proto_id 均為 2301 與 2203，沒有重複訂閱造成的重複事件。

總計 2,564 幀、8,159 事件、2,563 轉移，其中 2,555 筆合法，合法 64-step 起點為 2,240 個。跨回合 row 1207 無效；兩個 final 尾轉移皆無效且 bootstrap=0，因為此次是人工 reset／stop，不是任務 success。合法前綴仍可使用，全部 sequence 起點不跨 episode 或 gap。

九次 release_all 回傳成功。記錄到兩個 scheduler gap，沒有 no_free_buffer、GPU readback error 或 writer backpressure 事件；這是短流程計數，沒有據此宣稱長程品質 gate 通過。LogOutput 保留於 `runs/live/issue14-LogOutput.log`，包含首次未核准指紋的預期拒絕及既有 numcodecs 棄用警告；資料完成以實際檔案驗證為準。

| 證據檔 | SHA-256 |
| --- | --- |
| evidence/manifest.json | `9e5c4450bad137e4394005e107a73a7dedb7517cc15fd8592914a69099b476e4` |
| evidence/recording.mkv | `15d730020f76dfa7159653fcbad01e8310863b88c8446854bff2f90a0b623b53` |
| evidence/frames.ndjson | `c30b11365c739750d6ee326263165656c6cf9f3593f43044a95ae1f255e0b228` |
| evidence/events.ndjson | `f5ea8ccbe84b3004e5cac441ea64e9070cd799df037d89a87371eadcce7868c6` |
| dataset/dataset.json | `53ed1c7a9801c1f00163bdb624386957bf257c151ca9b01be0b996f87034955a` |

## 2026-09-10：30 分鐘自動超時

使用者自行操作，回報科技面板與暫停各約兩分鐘。來源為 `runs/live/4f3908b4-197f-404f-b835-a2f615b963cb.source`；沿用已核准的 DLL 與 trial。沒有使用 Computer Use，也沒有縮短 timeout 或修改證據。

| 項目 | 實測 |
| --- | --- |
| session_id | `c1ec3ae4-03b5-4db7-adf8-6b0626c32ce5` |
| attempt_id | `77e530e1-cadd-4076-9d69-7ca128dbcb36` |
| episode_id | `f75e7b54-83c8-4556-879e-fe21a54823a4` |
| 起點至 timeout | 1,800.0119748 秒 |
| paused 取樣累計 | 約 127.9768663 秒 |
| fullscreen_ui 取樣累計 | 約 256.1344991 秒（包含暫停 UI，不與 paused 相加） |
| 幀／事件 | 35,992／119,724 |
| final capture_id | 35991，擷取要求晚於 timeout 約 5.2589 ms |
| 控制釋放要求 | 5 次 succeeded=true |
| gap 事件 | scheduler 7 次，其餘類別 0 次 |

UI 時長按相鄰 input 取樣以左端狀態累加，屬取樣估計。起點為擾動後第一幀，而非 world_ready；即使 game tick 因暫停落後，仍在約 1,800 秒結束。這次直接驗證了 #14 的正常自動超時計時與 final observation，不代表 #21 的全部長程資源／吞吐驗收。

`tmp/verify-issue14-timeout.py` 已透過正式 `verify_recording` 完整解碼並核對 checksum，通過。evidence manifest SHA-256：`d9f2c501af23d5b13eb0ae29af6fd1e1c840e45451c1d5580f9bddf2d1071ce2`。

另記錄到不支援的 Space 按下 37 次、E 按下 2 次。來源 outcome 為 timeout；編譯時必須將未知控制之後的範圍標無效，而不能強制讓尾端 bootstrap=1。純合法 timeout 的 mask=1 仍由整合 fixture 覆蓋；此次資料不能冒充該項實機正例。

背景處理發布 COMPLETED 後，再以正式 `open_dataset` 完整讀回，退出碼 0。總計 35,991 筆轉移、112 筆合法前綴轉移；尾端為 `episode_outcome=timeout`、`truncation=true`、`is_terminal=false`、`validity_status=invalid`、`unknown_control`、`bootstrap_mask=0`，符合無效尾端不 bootstrap 的規則。dataset.json SHA-256：`a8ba1c50d857404837e558782560beb3c8c1f97de4466b6245ea1c06866815e8`。機器可讀結果保存於 `runs/live/issue14-timeout-verification.json`。

結論：30 分鐘計時包含暫停與 UI、final observation、timeout 與有效性分離已取得實機證據；不必為計時項目重錄。本次尚未涵蓋人工介入、注入失敗與 recorder fault 的受控實機測試，也沒有量測 #21 要求的完整資源／容量指標。
