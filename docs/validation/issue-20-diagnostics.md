# Issue #20 專用診斷操作

這份流程適用新增 Diagnostics.Case 的版本。由使用者操作 DSP，不使用 Computer Use。診斷會真的注入 W、觸發錄製器停用或銷毀，但不修改存檔。請使用 Starting Save。

## 先部署並重新校正一次

插件 DLL 已改變，舊 runtime fingerprint 與舊校正不能用在新版。先關閉 DSP，在 `E:\GitHub\DSP_Dreamer` 的 PowerShell 執行：

```powershell
.\tools\deploy-recorder.ps1 -Diagnostics
```

1. 啟動 DSP 並載入 Starting Save，按一次 F6 產生新的 `runs/live/runtime-candidate.json`。
2. 核對候選環境，取得 SHA-256，填入遊戲 Config 的 `[Recording] ApprovedFingerprint`：

```powershell
(Get-FileHash .\runs\live\runtime-candidate.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

Config 路徑：`E:\Steam\steamapps\common\Dyson Sphere Program\BepInEx\config\tw.jaywu.dspdreamer.recorder.cfg`。

3. 保持 `[Diagnostics] Case = full`，回 DSP 按 F6。不要操作鍵鼠，等完整探針自動停止及發布。
4. 傳回錄製 ID 供核對。完整校正必須重新通過；新校正檔與 SHA 填入 `[Control] CalibrationFile`／`ApprovedCalibration`。自行執行可用下列指令，請將 `<ID>` 替換成實際 ID；輸出不可覆寫：

```powershell
.\.venv\Scripts\python.exe tools\verify-control.py --dataset "runs\live\<ID>.source.dataset" --out "runs\issue20-new-calibration.json" --calibration
(Get-FileHash .\runs\issue20-new-calibration.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

## 每次只執行一種案例

新版完整校正已由錄製 `2a05b2a4-6291-4f10-a12c-407ddb670ad4` 通過正式 dataset 讀回及校正發布：44／44 模型要求、45／45 必要釋放，延遲 12.6841–17.4198 ms，MouseLeft held 217.5703 ms，NumPad1 讀為 End 並通過區分。DLL SHA-256 為 `17043a1ca5b2832df4f3541a7716bb2e6ba03d6ad9f1f4ec9f6ccfab571cf3e2`，與本機 Release 建置一致；runtime fingerprint 為 `592974525a9245d33c0f813e4cab69d08358fd819afb382726565610c9fdb8c0`。

本機校正檔為 `E:\GitHub\DSP_Dreamer\runs\issue20-2a05b2a4-calibration.json`，SHA-256 為 `384f3b698ae205338d0b37b936f6fd9e1d72b8d1ba60ef7a83eaea58fa213608`。來源 checksum 與逐筆 sample refs 見[新版校正證據](issue-20-diagnostics-calibration-live.json)。使用者須將路徑與 SHA 填入 Config；四項專用診斷尚待實機驗證。

錄製停止並發布完成後才改 Config。F6 開始時會重新讀取 Config；Case 不改變環境指紋，不需要每切換一次就重新校正。F6 的專用案例會自動停止，**不需要 F7、F8 或 Shift+F10**。

```ini
[Diagnostics]
Enabled = true
Case = focus_hold
```

| Case | 使用者操作 | 預期結果 |
| --- | --- | --- |
| `focus_hold` | 載入 Starting Save，按 F6。基準重載後看到機甲持續前進，等約半秒，Alt+Tab 切出去，約一秒內回 DSP。其餘不要操作。 | 模型 W 在失焦前確實 held；失焦後釋放，回焦不恢復注入。30 秒內未切換則停止且該項驗證不通過。 |
| `final_readback` | 改 Case，按 F6，等待自動完成。 | W 約按住一秒後結束，只讓結束後的 final capture 讀回失敗；`recorder_fault`、`incomplete`、final capture 為 null。 |
| `disable` | 改 Case，按 F6，等待獨立診斷檔完成。 | 真正設定 Recorder 元件 `enabled=false`，觀察實際 OnDisable 回呼、釋放與後續輸入。完成後關閉並重新啟動 DSP。 |
| `destroy` | 重啟 DSP、載入基準，改 Case 後按 F6，等待獨立診斷檔完成。 | 真正呼叫 Unity Destroy 移除 Recorder 元件，獨立觀察 OnDisable／OnDestroy 回呼、釋放與後續輸入。完成後關閉並重新啟動 DSP。 |

停用／銷毀時，獨立元件會維持 finalization、觀察 VFInput 後的輸入。這證明 Recorder 元件的 Unity 生命週期回呼，並不表示 Mono 已從程序卸載整個 DLL。不要在測試期間關閉遊戲或替換 DLL。

等待 `BepInEx/LogOutput.log` 出現 `DSP diagnostic evidence completed:`。一般還需等正式錄製、編譯、讀回完成；最長等待 180 秒。若看到 `FAILED`、沒有完成標記或沒有 dataset，保留錄製 ID、日誌與工作檔供追查，不算通過。診斷檔會先逐行落盤，程序提前結束不會留下假的完整結果。

每次傳回「ID，Case 測試」。資料在：

- `runs/live/<ID>.source.evidence` 與 `.source.dataset`：正式證據及編譯資料。
- `runs/live/<ID>.source.diagnostic.ndjson`：獨立觀察、回呼、控制要求及發布結果。
- `runs/live/<ID>.source.diagnostic.ndjson.complete.json`：獨立診斷檔 checksum。

核對專用案例請加 `--diagnostic`，不要用完整校正 gate 判斷故障測試是否成功：

```powershell
.\.venv\Scripts\python.exe tools\verify-control.py --dataset "runs\live\<ID>.source.dataset" --diagnostic "runs\live\<ID>.source.diagnostic.ndjson" --out "runs\issue20-<ID>-diagnostic-report.json"
```

核對器會檢查來源與 runtime 身分、checksum、實際 W held、結束後釋放及空 held 觀察；停用／銷毀還要求回呼內有釋放與回呼完成後的觀察。最後影像失敗必須對上正式 dataset 的缺失 capture，不能以一般讀回故障替代。

## 測完恢復

首次 `focus_hold` 錄製 `818cff2d-6441-4fe7-b13e-7868c28a0266` 已完成正式 dataset 與獨立 journal 核對。8 項檢查中 7 項通過：W down／held、失焦原因、釋放、無後續注入及發布均確認，首筆空 held 距結束 50.3271 ms。唯一未通過為 `refocused_empty`；失焦後 177 筆觀察全為 focused=false，最後一筆約在結束後 2.99 秒，不能推定未觀察到的回焦狀態。保留 gate=false，報告見[首次持續按鍵失焦證據](issue-20-focus-hold-attempt-live.json)。

重測不必更動 Config 或重新校正。切出去後放開 Alt／Tab，再重新按一次 Alt+Tab 切回，盡量在一秒內完成；釋放動作會清除 Alt，不能依靠一直按住 Alt 再按 Tab。回 DSP 後放開所有按鍵並等待診斷完成。

重測 `aeee40ac-f49d-4eb6-9790-8ac04a5168e4` 的正式 dataset 與獨立 journal 核對通過，8／8 checks 為 true，`gate_passed=true`。W 注入與實際 down／held 已確認；失焦後三次釋放分別為 28／28、24／24、24／24，43.3781 ms 後 held 清空。回焦首筆 index 412 的 held／down／up 全空，沒有後續模型要求，final capture 45 存在。episode 保留 `invalid`／`focus_loss`／`unknown_control`（切換視窗用的非模型按鍵不作訓練），不影響本項專用故障核對。完整結果與 journal checksum 見[持續按鍵失焦通過證據](issue-20-focus-hold-live.json)。下一項為 `Case = final_readback`，F6 後不操作，等待自動發布。

重啟 DSP，將 Case 改回 `full`，再按 F6 跑一次完整探針，確認插件重啟後仍正常。要恢復正常人工 F8 錄製時，設定 `Enabled = false`，並保留本版已核准的 CalibrationFile／ApprovedCalibration。專用診斷的結果不供訓練，也不會替換校正檔。

## 離線驗證與審查

2026-09-11：完整 pytest 136 項通過，139.44 秒，JUnit 存於本機 `tmp/issue20-diagnostic-tests-final.xml`。其中 8 項診斷核對測試涵蓋 checksum／錄製身分、缺失回呼與釋放、零封包或缺 down、失焦清空與回焦殘留、final capture 故障位置及錯誤收錄。mypy 16 檔通過，Release 建置 0 warnings／0 errors。這些離線結果不取代新版實機操作。

規範審查：無硬性違規或阻擋項目；保留固定 Case 的直接分派，不新增 handler 架構。規格審查：已修正只憑 held 判定注入、以及 Unity 失焦清空可能造成誤判的兩項問題；複核無剩餘阻擋。獨立 observer 保存 down／held／up，要求 W 確實送出 1／1 且被讀到 down／held，失焦則核對最後一筆 focused input。
