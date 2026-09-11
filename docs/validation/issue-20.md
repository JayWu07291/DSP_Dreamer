# Issue #20 控制路徑與人工實機驗證

目前已實作 v3／20 維模型動作注入、校正探針與正式資料讀回核對。實機完整校正已通過，故障／卸載案例仍待驗收，不宣稱本票全部通過。依使用者要求，由使用者操作遊戲，不使用 Computer Use。

## 契約與前置證據

沿用 #12 與 #10，並採用 #14 追加 Space／E、#18 已驗收的 `action_catalog_v3`。已核對 [#18 驗收報告](issue-18.md)及其完整流程、重試資料，沒有以 issue 關閉狀態代替品質證據。

鍵盤使用 set-1 scan code，Digit1／Digit2 分別是 `0x02`／`0x03`。NumPad1 的 `0x4F` 只用於診斷，不能成為模型控制。MouseLeft／Right／Middle、相對移動與垂直 wheel 使用原生封包。每次注入和釋放記錄 requested／sent count、request ticks；實際動作仍來自 `VFInput.OnUpdate` 後的 `input`，不以成功送出數取代 DSP 觀察。

原生 API 依 Microsoft 的 [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)、[KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput)及 [MOUSEINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput) 定義。SendInput 的回傳數表示已插入 Windows 輸入串流，不代表遊戲已接收；UIPI 阻擋也不能只靠 error code 辨認。

## 由你操作

以下指令在 `E:\GitHub\DSP_Dreamer` 的 PowerShell 執行。先關閉 DSP。

```powershell
.\tools\deploy-recorder.ps1 -Diagnostics
```

部署腳本先備份既有 DLL／設定，再編譯部署。它會清空 `ApprovedFingerprint`，不自動核准環境或校正。

1. 啟動 DSP，載入已存在的 `Starting Save` 基準存檔。確認沒有其他錄製或控制工具正在送鍵鼠。不需要數字鍵盤或 Num Lock 鍵，87 配列也能執行；NumPad1 探針由程式注入。
2. 按一次 **F6**。第一次會因環境尚未核准而拒絕，並寫出 `runs/live/runtime-candidate.json`。
3. 檢查候選中的遊戲、Unity、插件與 `globalgamemanagers` 雜湊、DSP 設定、畫面尺寸及 `windows_mouse_settings`。陣列順序為 sensitivity、threshold1、threshold2、acceleration。用下列指令取得 SHA-256，再把值填入 `E:\Steam\steamapps\common\Dyson Sphere Program\BepInEx\config\tw.jaywu.dspdreamer.recorder.cfg` 的 `[Recording] ApprovedFingerprint`。

```powershell
(Get-FileHash .\runs\live\runtime-candidate.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

4. 回到 DSP，將游標放在不會點到按鈕的空白位置，再按 **F6**。錄製器重新載入基準，第一張有效 RGB 後等待一秒，依序測 20 個控制、兩軸各 11 個 mouse bins、正負 wheel 與 NumPad1。每次按住及放開各等 200 ms，探針本身約 18 秒，載入和發布另計。Escape 排在按鍵探針最後，避免後續左鍵點擊暫停選單。
5. 期間不要操作鍵鼠或切換視窗。要中止可按 **F8**；失焦也會終止並釋放。這類中止錄製保留供失敗核對，不可當作完整校正。
6. 自動停止後等待 `BepInEx/LogOutput.log` 出現 `Recording, compilation, and readback completed`。記下該行的 `.source` 路徑。其旁應有 `.source.evidence` 與 `.source.dataset`。
7. 將下列 `<錄製ID>` 換成實際目錄名稱。先輸出完整核對報告，再嘗試發布校正。輸出檔不可覆寫，重跑請使用新檔名。

```powershell
.\.venv\Scripts\python.exe tools\verify-control.py --dataset "runs\live\<錄製ID>.source.dataset" --out "runs\issue20-control-report.json"
.\.venv\Scripts\python.exe tools\verify-control.py --dataset "runs\live\<錄製ID>.source.dataset" --out "runs\issue20-calibration.json" --calibration
```

8. 校正發布必須通過全部控制、NumPad1 區分、兩軸 bins、wheel、實際 down／held、放開、左鍵至少 100 ms 及 requested-to-observed ≤100 ms。NumPad1 的 scan code `0x4F` 可讀成 `Keypad1` 或 `End`，但不能讀成 `Digit1`。科技面板等會呼叫 `VFInput.ResetAllAxes`，新版會保存 `game_input_reset`；只有已觀察到正確按下，且後續清空能對上重設紀錄，才接受遊戲消耗了按壓。原始 action 的 ambiguity 不會被修掉，左鍵最短時間也不放寬。Synthetic recording 永遠不能核准實機校正。請將報告或路徑提供給我核對；失敗時保留四檔 evidence，不修改原始輸入或把 `gate_passed` 手改為 true。
9. 校正核對後，在 `[Control]` 填入下列設定。SHA-256 使用實際校正檔的值。關閉 `[Diagnostics] Enabled` 後，**F8** 才是正常人工錄製入口。

```ini
[Control]
CalibrationFile = E:\GitHub\DSP_Dreamer\runs\issue20-calibration.json
ApprovedCalibration = <校正檔的SHA-256>
NativeScaleX = 1
NativeScaleY = -1
```

```powershell
(Get-FileHash .\runs\issue20-calibration.json -Algorithm SHA256).Hash.ToLowerInvariant()
```

遊戲或插件重建、DSP／Windows 滑鼠設定、畫面尺寸、NativeScaleX／Y 改變後，舊指紋或校正會被拒絕，須重新執行以上步驟。NativeScaleX／Y 保留原生位移調整入口；模型的 observed-to-pixel 比例仍固定為 20.0，不能藉由更改模型 codec 讓不合格校正過關。

## 另存故障案例

保留一份完整探針後，再另開 F6 錄製分別測試下列情境。每次都等發布完成再開始下一次，並記下案例與 `.source` ID。這些報告預期不通過完整校正。

| 操作 | 應核對的證據 |
| --- | --- |
| 測試中按 F8 | `stopped`、release count、之後沒有 held |
| 測試中切到其他視窗 | `focus_loss`、立即釋放；回到 DSP 不再繼續送模型動作 |
| 測試中按 F9 | `reset`、釋放、相同 trial manifest、新 attempt／episode |
| 啟用 Diagnostics，測試中按 Shift+F10 | `simulated=true` 的 injection failure、實際 release 重試及 episode 原因 |
| 啟用 Diagnostics，測試中按 F7 | 受控 readback 例外、`recorder_fault`、釋放與 final observation／incomplete 狀態 |
| 測試中退出至主選單 | `world_unloaded`、釋放；使用新錄製檢查重載後仍可正常測試 |

插件卸載路徑已有 `OnDisable`／`OnDestroy` 釋放，但仍需專用實機測試；直接殺掉程序不能證明 managed 卸載回呼有執行。不要在錄製期間替換 DLL。人工中止只算故障證據，不能算代理完成微任務。

## 程式介面與驗收界線

`StartPolicyRecording()` 與 `SubmitAction(catalog, binary, mouse, wheel, captureTicks, inferenceTicks)` 供 Unity 主執行緒呼叫。Policy 與 human mode 在工作階段開始時固定，不能於人工錄製中切換注入。第一動作必須為 no-op；佇列容量一筆，不覆寫未送出的動作。相鄰提交原生控制至少間隔 100 ms，超過 capture deadline 或缺少下一動作時釋放並終止該次嘗試，保留 `deadline_miss`。安全停止不受最短按住限制。

後續推理 runner 尚未實作。本票不宣稱完成 #31 的完整閉迴路 deadline、30 分鐘資源量測或任何模型品質 gate。F6 是受控校正，不是 policy 成果；其 `diagnostic_mode=true`，正式 compiler 不把這些轉移納入訓練。

離線測試從 synthetic evidence 經四檔發布、正式 compiler、dataset loader 核對要求與實際輸入不同、partial SendInput、缺 down、殘留 held、過早放開及禁止 synthetic 校正。C# 執行檔另核對完整控制順序、scan codes、mouse bins 與全部兩鍵組合，拒絕舊 catalog。它們不能代替上述實機案例。

2026-09-11：最終完整 pytest 共 124 項通過，耗時 142.97 秒，包含 10 項控制測試。JUnit 存於本機 `tmp/issue20-tests-final.xml`。mypy 15 個原始碼檔案通過，Release 建置 0 errors／0 warnings。這些數字均為離線檢查，尚無 #20 新實機錄製、校正核准或實機故障驗收結果。

```powershell
dotnet restore tests/ControlReplay/ControlReplay.csproj
.\.venv\Scripts\python.exe -m pytest tests/test_control.py -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore --configuration Release
```

## 首次實機探針追查

錄製 `c14ac7c4-cba9-4fe5-88e9-39fa987f0579` 的 44 筆模型要求通過 43 筆，45 次必要釋放全部通過。失敗要求為 T，sequence 555 已有 down／held，但 559 起變成空 held 且沒有 up。安裝版 `UITechTree._OnOpen` 呼叫 `VFInput.ResetAllAxes`，舊錄製未保存該呼叫，故保留不合格，不推定為正常。

NumPad1 探針 sequence 2294 注入 `0x4F`，2295 讀到 End down／held，2319 讀到 End up，沒有混成 Digit1。修正核對器後此區分已通過；新報告另存 `runs/issue20-control-report-v2.json`，原報告及 evidence 不變。整份錄製仍因缺少 T 的重設證據而不發布校正。87 配列鍵盤不必手動按 Num Lock。

新版本須重新部署、核准新的 runtime fingerprint，再以 F6 重錄。補上的整合測試確認已記錄的 reset 可核對、未記錄的狀態消失仍拒絕、End／Keypad1 均與 Digit1 區分，且不改寫實際動作與訓練有效性。

本次修正後完整 pytest 128 項通過，耗時 138.81 秒，結果存於本機 `tmp/issue20-reset-tests.xml`。mypy 15 檔及 Release 建置通過，規格複核無阻擋問題。新增 reset 掛點的實機驗收仍須使用新錄製完成。

## 新版實機校正通過

使用者操作的新錄製為 `a22f366b-4b69-4a1a-a4bf-8c4d122fd72b`。正式 dataset loader 完整核對編譯產物，再執行 `inspect_control` 及 `publish_calibration`，兩者 `gate_passed=true`。

| 核對項目 | 結果 |
| --- | --- |
| 模型要求 | 44／44 確認，含全 20 控制、兩軸各 11 bins 與正負 wheel |
| 必要釋放 | 45／45 確認 |
| requested-to-observed | 最小 10.7556 ms，最大 17.8047 ms |
| MouseLeft 實際 held | 217.1833 ms |
| T | request 6 對上 game reset sequence 551 |
| NumPad1 | probe sequence 2297，DSP 讀為 End，與 Digit1 區分通過 |
| observed-to-pixel | 兩軸固定 20.0 校正核對通過 |

原始四檔位於 `runs/live/a22f366b-4b69-4a1a-a4bf-8c4d122fd72b.source.evidence`；正式編譯資料為同名 `.source.dataset`。完整報告為 `runs/issue20-a22f366b-report.json`，校正檔為 `runs/issue20-a22f366b-calibration.json`。來源身分、checksum 及逐筆 sample refs 保存於[校正證據](issue-20-calibration-live.json)。

校正檔 SHA-256 為 `c6daeaab53ecef6e3cfaf5d1b8ec38c3cc3978a91ced7f9361ab4a803b52822d`，綁定 runtime fingerprint `b42526a710b82d2dae98140cd36d333664b7aef9c063a29cf14ba2b942ce0848`。尚未替使用者寫入遊戲設定；須填入 CalibrationFile／ApprovedCalibration 才會啟用。此錄製是診斷校正，不是代理成果。失焦、停止、重設、故障、卸載的另存案例仍待完成。

## F8 停止案例

錄製 `37392605-2ec5-4d63-a7bd-1cbf2977fff5` 已由正式 dataset loader 讀回。結束原因為 `stopped`，兩次停止後 release 分別送出 25／25、24／24 個封包。結束後 16.7971 ms 的首筆 input 已無 held，之後另外兩筆也保持空 held；沒有後續模型要求，final capture 130 存在。`validity_status=invalid`、reason `stopped` 符合人工中止的定義。

本次確認停止流程及觀察範圍內無殘留。停止前模型控制已放開，當下僅有 F8，尚未證明模型按鍵仍 held 時被強制釋放。完整校正報告為 false，不代表此停止流程失敗。來源 checksum 與逐筆依據見 [F8 停止證據](issue-20-stop-live.json)。

## 失焦案例

錄製 `552926a4-5c94-4021-a4bd-ca64c6f185d4` 已由正式 dataset loader 讀回。sequence 513 以 `focus_loss` 結束 episode，隨後兩次 release 送出 28／28、24／24 個封包；34.8048 ms 後首筆 input 的 held／down／up 全空。回焦首筆 sequence 896 也全空，episode 結束後沒有任何模型要求。最後 F8 發布另送出 25／25 個釋放封包，final capture 56 存在，episode 保留 `invalid`／`focus_loss`。

回焦後 sequence 973／979 另有一次新的 MouseLeft down／up，並非持續殘留。失焦前最後送出的模型要求是 R，但當時 input 只觀察到 LeftAlt，因此尚未證明模型按鍵仍 held 時的強制釋放。這次確認失焦終止、釋放呼叫及回焦不恢復模型注入；完整校正 gate 為 false 符合中途停止的案例。來源 checksum 與逐筆依據見[失焦證據](issue-20-focus-live.json)。

## F9 重設與持續按鍵釋放案例

錄製 `567f2e12-cd30-4a6f-9a4d-0cc6a6404f75` 已由正式 dataset loader 讀回。第一個 episode 以 `reset` 結束，final capture 58 存在；sequence 1594 仍讀到 R／F9 held，1596 成功釋放 26／26 個封包，1599 讀到 R／F9 up 且 held 清空。重載前另兩次釋放皆為 24／24。

同一份 trial manifest 下建立新的 attempt／episode，world binding 由 4 變成 5，兩次 `perturbation_applied` 的 camera／mecha yaw 相同。重設至新 episode 開始之間沒有模型要求，sequence 1832 才在新 episode 恢復探針。

第二個 episode 最後由 F8 以 `stopped` 結束，final capture 176 存在。sequence 2441 仍讀到 E／F8 held，2443 成功釋放 26／26 個封包，2446 讀到 E／F8 up 且 held 清空，後續兩筆保持空 held，沒有後續模型要求。本次補足 F8 在模型按鍵仍 held 時的釋放證據；失焦的相同情境仍未涵蓋。兩個 episode 均保留 invalid 與各自原因，不作完整校正或代理成果。來源 checksum 與逐筆依據見 [F9 重設證據](issue-20-reset-live.json)。

下一個人工案例：F6 開始探針，自動操作開始後按 Shift+F10，放開按鍵、等一秒，再按 F8 完成發布，核對模擬注入失敗與實際 release 重試。F6 已啟用診斷模式，不必修改 Config。

## 注入失敗測試未觸發：人工介入證據

錄製 `67763ac3-f286-4f93-b094-8793415c3d06` 已由正式 dataset loader 讀回，但實際 diagnostic case／episode reason 為 `human_intervention`。sequence 2970 讀到 LeftShift down，2977 探針 release 成功送出 27／27，2980 讀到 LeftShift up；3007 讀到 F10 時已沒有 Shift。故本次沒有模擬 release failure，也沒有故障重試證據，不可算注入失敗驗收。

介入後 release 成功送出 26／26，首筆 input 在 22.0454 ms 後 held 清空，無後續模型要求，final capture 65 存在。逐筆依據與來源 checksum 見[人工介入證據](issue-20-intervention-live.json)。重試 Shift+F10 時應快速連按兩鍵，避免提前長按 Shift 被探針釋放；這是目前快捷鍵操作的限制。

## 規範審查

無書面規範硬性違規。審查列出四項非阻擋性的簡化建議：C#／Python 契約重複、mode 字串分派、動作欄位群組與 `Pixel` 命名。跨語言契約以 parity 測試核對；單筆佇列使用 `PendingAction` 保存欄位。本次保留三種 mode 的直接分派，未新增 handler 架構。另發現 `rejected`／`deadline_miss` 可能未影響 gate，已納入失敗報告並增加測試。

## 規格審查

三項程式缺口已修復：SubmitAction 的過期 capture 明確記 `deadline_miss`；停止發布前重驗完整輸入設定身分；核對區間以 `[start,end)` 包含同 tick 的起點輸入。起點案例回歸通過。實機全控制、故障／卸載釋放與實際注入延遲仍待上述人工驗證，不以離線測試替代。
