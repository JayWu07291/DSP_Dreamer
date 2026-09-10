# Issue #14 受控故障測試

2026-09-10：三項受控實機測試與完整讀回已通過。使用者自行操作；不使用 Computer Use。這次加入的 Space／E 是正常動作，F7／F10／Shift+F10 仍不是模型動作。

## 實測結果

來源 `runs/live/4343f377-0861-4906-9137-ed2cbd6835e7.source`，commit `4aacd4b`；本次實測用 F10／F11／F7。使用者確認三項皆能中斷 W 移動，並指出 F11 同時是 DSP 隱藏 UI 鍵。因此後續入口改為 Shift+F10；新快捷鍵僅完成建置驗證，尚未部署或實機測試。

正式 `verify_recording` 完整解碼、checksum 與 `open_dataset` 讀回通過：995 幀、7,367 事件、994 筆轉移，同一 trial 三個不同 attempt／episode。原因依序為 human_intervention、injection_failure、recorder_fault；final capture ID 為 536／765／995，皆晚於各回合結束。一次模擬 release 失敗後，緊接的真正 release 成功。GPU 失敗造成 capture ID 缺口，且 final observation 存在（沒有額外 gap 事件）。

Space 按下 8 次、E 按下 2 次，20 維動作的 index 18／19 均有非零資料。全部轉移 valid=false、bootstrap=0、sequence_starts 為空，符合診斷隔離。可重跑檢查為 `tmp/verify-issue14-controlled.py`；結果保存於 `runs/live/issue14-controlled-verification.json`。F11 的 UI 副作用不否定 release 重試證據，但此次不是無 UI 副作用的快捷鍵測試。

## 部署與隔離

先關閉 DSP，由 agent 部署 `tools/deploy-recorder.ps1 -Diagnostics` 並備份既有插件及設定。使用者重新啟動遊戲、載入 `Starting Save`、按一次 F8 產生候選指紋，再由 agent 核對並核准。下列流程要等核准完成才開始。

診斷模式在每次錄製開始時固定。來源 metadata 的 `diagnostic_mode=true` 會傳到 dataset；compiler 將全段 `valid=false`、bootstrap=0，loader 也會拒絕被錯誤標成可訓練的診斷轉移。因此此次只驗證環境收尾，不拿這些片段當示範資料。

## 操作順序

1. 按 F8 開始診斷錄製，等自動載入完成。操作 Space 跳躍一次、E 開關背包一次，再等待至少五秒，作為 v3 真實輸入證據。
2. **人工介入：**在空地按住 W，按一次 F10，觀察機甲是否停止；放開 W，等待兩秒。不要切換視窗。回報是否有持續移動或無法操作。
3. 按 F9 重試，等待基準重載完成，正常操作至少五秒。
4. **注入失敗：**按住 W，按一次 Shift+F10，觀察機甲是否停止；放開 W，等待兩秒。第一次釋放要求會被測試入口故意跳過並記為失敗，隨即走真正的 SendInput 重試釋放。
5. 按 F9 再重試，等待基準重載完成，正常操作至少五秒。
6. **錄製故障：**按住 W，按一次 F7，觀察機甲是否停止；放開 W，等待兩秒。下一次 readback callback 會走例外收尾，嘗試再取得 final observation。
7. 按 F8 結束工作階段，等待背景封存完成；回報「受控測試完成」，並分別列出三次是否仍有殘留移動、是否出現遊戲錯誤。

測試只使用短回合，不用再等待 30 分鐘。不覆寫 `Starting Save`，不用 F12、不強制終止程序或製造磁碟故障。完成後由 agent 關閉診斷設定。

## Agent 核對項目

- 同一 session 三個不同 attempt／episode，trial 與 split group 不變。
- 各回合各有一次 `control_request.operation=diagnostic_fault`，case 依序為 human_intervention、injection_failure、gpu_readback_error，並標明 simulated=true。
- 人工介入：reason=human_intervention，release_all 成功，對照觸發前後 W 的實際 input；注入失敗：一次 simulated release false，緊接一次非 simulated release true，reason 保留 injection_failure。
- readback 故障：capture ID 有缺口且後續 final observation 存在；reason=recorder_fault，來源／四檔 evidence 能完整驗證。這個案例不代表已測到 fatal writer、磁碟或程序終止恢復。
- Space／E 原始輸入保存，v3 二進位 index 18／19 正確；不可因診斷轉移不可訓練而把 action 靜默歸零。
- 全資料集 diagnostic_mode=true，所有 valid=false、bootstrap=0、sequence_starts 為空；不把故障注入測試資料放入訓練。

受控故障證明的是正常程序中的錯誤分支與釋放路徑，不是硬體故障發生率或任意 OS／磁碟故障下的恢復保證。缺 final observation 與 fatal writer 的實機注入不包含在上述三個案例；其目前覆蓋範圍仍以 #14 報告與後續 #17 恢復工作為準。
