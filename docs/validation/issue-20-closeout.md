# Issue #20 結案驗收

2026-09-12：六項驗收要求完成。適用 action_catalog_v3／20 維，沿用 [#18 修訂](https://github.com/JayWu07291/DSP_Dreamer/issues/18#issuecomment-5631697852)及 #14 追加 Space／E 的決議；#20 原文 v2 是未同步的舊名稱。

## 要求與證據

| #20 驗收要求 | 完成依據 |
| --- | --- |
| 實體 scan code、低階滑鼠；要求與實際輸入分開 | `ModelAction.cs`／`PolicyControl.cs`；控制要求保存為 control_request，訓練動作取 DSP input。`test_requests_never_replace_observed_training_labels` 驗證注入要求與實際讀取不同時不能以要求替代。 |
| 全部控制、Digit1／Digit2、NumPad1 及釋放 | [新版校正](issue-20-diagnostics-calibration-live.json)與[重啟完整探針](issue-20-destroy-restart-live.json)：44／44 模型要求、45／45 必要釋放，涵蓋 20 控制。Digit1=0x02，NumPad1 讀為 End 且與 Digit1 區分。 |
| 滑鼠 bins、設定與 fingerprint 校正綁定 | 新版完整校正覆蓋兩軸 11 bins 與正負 wheel，固定 observed-to-pixel=20.0；`CheckCalibration` 驗證檔案 SHA、catalog、fingerprint 及尺度，開始／執行／停止路徑核對設定身分。 |
| UI 左鍵至少 100 ms、禁止組合、人工／policy 互斥 | 新版校正 MouseLeft held 217.5703 ms；重啟探針 217.5196 ms。ControlReplay 與 Python parity 測試核對全部兩鍵組合。新增 ControlGuards 直接執行已部署 DLL 的公開 API 防護，人工錄製中 policy start／submit 均拒絕，原 mode、active 與 pending action 不變。 |
| 注入數、延遲、失敗／失焦／停止／重設／例外／卸載釋放 | [F9 與 held-key F8](issue-20-reset-live.json)、[持續按鍵失焦](issue-20-focus-hold-live.json)、[注入失敗重試](issue-20-injection-failure-live.json)、[讀回故障](issue-20-readback-failure-live.json)、[世界卸載](issue-20-world-unload-live.json)、[OnDisable](issue-20-disable-live.json)、[OnDestroy](issue-20-destroy-live.json)皆有實機證據。新版完整校正延遲 12.6841–17.4198 ms；重啟探針 11.0517–17.9896 ms。 |
| 正式錄製、編譯讀回，要求／觀察／故障一致 | 所有實機證據均由正式 dataset loader 核對；[final observation 故障](issue-20-final-readback-live.json)確認缺失 capture 與 incomplete 一致。四項專用診斷通過，銷毀後重啟完整探針通過。診斷資料不供訓練，也不算代理成果。 |

## 互斥驗證的範圍

新增測試分別使用當前原始碼的 Release 建置與目前部署於遊戲目錄的 DLL；已部署 DLL，其 SHA-256 為 `17043a1ca5b2832df4f3541a7716bb2e6ba03d6ad9f1f4ec9f6ccfab571cf3e2`，與已驗收 runtime 相同。以 Mono.Cecil 建立只在記憶體中的副本：Emit 不寫 Unity 日誌；InjectAction、ReleaseControls、StartRecording 改為碰到即失敗的副作用邊界。`StartPolicyRecording`／`SubmitAction` 的 IL 與被測 guard 不改動。這是公開 API 防護的離線測試，不是額外實機 policy 執行。

測試涵蓋人工 active 時拒絕 policy start／submit、發布 writer 尚存在時拒絕重開、非 Unity 主執行緒拒絕呼叫，以及拒絕後不改動人工工作階段。正式插件原始碼與已部署檔案均未因本次收尾而修改，不需要重新部署或校正。普通人工短錄製不是 #20 新增的結案條件。

```powershell
dotnet restore tests/ControlGuards/ControlGuards.csproj
.\.venv\Scripts\python.exe -m pytest tests/test_control_guards.py -q
.\.venv\Scripts\python.exe -m pytest -q --junitxml=tmp/issue20-closeout-tests.xml
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
```

## 驗收界線與交接

本次完整 pytest 137 項通過，143.07 秒，JUnit 位於本機 `tmp/issue20-closeout-tests.xml`；當前原始碼建置與已部署 DLL 的互斥測試另行通過（1 項測試，1.97 秒）；兩次拒絕後各自核對非 null pending action 的 reference、全部欄位與按鍵內容。mypy 16 個原始碼檔案通過，Release 建置 0 warnings／0 errors。重建的本機 DLL 可能因 Git revision metadata 改變而有不同 hash，不可拿它替換目前已校正的部署而略過指紋檢查。

- 注入失敗為受控模擬，實際執行釋放重試；不宣稱已重現所有 Windows／UIPI 原生失敗。
- 插件卸載證據為 Unity Recorder 元件的 OnDisable／OnDestroy；不宣稱強制終止程序時 managed 回呼仍可執行，也不宣稱從 Mono 卸載整個 assembly。
- OnDestroy 案例首筆空 held 在結束後 204.1987 ms、回呼完成後 13.2345 ms。中間沒有 input 樣本，不能將前者當作 Windows 實際釋放延遲。
- 早期故障案例使用當時 DLL，新版補驗與完整重啟結果分別保存；每份證據保留自身 runtime 與限制，沒有改寫舊結果。
- 後續 policy runner、完整閉迴路 deadline／資源測量及模型品質由後續票驗收，本票不宣稱 #31 gate 通過。
- 正常人工錄製使用 `Enabled=false`、`Case=full`，保留新版已核准校正。完整示範資料收集與訓練不屬本次結案要求。

完整實機操作、錄製 ID 與逐次追查見[專用診斷紀錄](issue-20-diagnostics.md)及[歷史實作紀錄](issue-20.md)。大型原始 evidence／dataset 保留本機 `runs/live`，不隨 Git 上傳；Git 內保存核對報告、checksum、來源 ID 與 sample refs。
