# Issue #14 受控故障測試

2026-09-10：已準備測試入口，實機結果尚未取得。使用者自行操作；不使用 Computer Use。這次加入的 Space／E 是正常動作，F7／F10／F11 仍不是模型動作。

## 部署與隔離

先關閉 DSP，由 agent 部署 `tools/deploy-recorder.ps1 -Diagnostics` 並備份既有插件及設定。使用者重新啟動遊戲、載入 `Starting Save`、按一次 F8 產生候選指紋，再由 agent 核對並核准。下列流程要等核准完成才開始。

診斷模式在每次錄製開始時固定。來源 metadata 的 `diagnostic_mode=true` 會傳到 dataset；compiler 將全段 `valid=false`、bootstrap=0，loader 也會拒絕被錯誤標成可訓練的診斷轉移。因此此次只驗證環境收尾，不拿這些片段當示範資料。

## 操作順序

1. 按 F8 開始診斷錄製，等自動載入完成。操作 Space 跳躍一次、E 開關背包一次，再等待至少五秒，作為 v3 真實輸入證據。
2. **人工介入：**在空地按住 W，按一次 F10，觀察機甲是否停止；放開 W，等待兩秒。不要切換視窗。回報是否有持續移動或無法操作。
3. 按 F9 重試，等待基準重載完成，正常操作至少五秒。
4. **注入失敗：**按住 W，按一次 F11，觀察機甲是否停止；放開 W，等待兩秒。第一次釋放要求會被測試入口故意跳過並記為失敗，隨即走真正的 SendInput 重試釋放。
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
