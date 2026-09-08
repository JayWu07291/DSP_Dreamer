# Issue #13 驗證報告

2026-09-08 狀態：實作已完成，合成資料的整合驗證通過。新的實機錄製仍待驗收；在該份證據通過驗證前，Issue #13 必須保持開啟。

## 自動化檢查

- 公開介面的完整測試套件：13 項通過，耗時 20.47 秒。
- Python 型別檢查：七個原始碼檔案均無問題。
- Release net472 建置：零警告、零錯誤。
- 已部署 DLL 的 SHA-256：`7f705deb9624457036cefba8f4717ff574bbbafe0412a322c8439058cb5d73f9`。

測試涵蓋回呼逆序時的擷取要求身分、相鄰 RGB 觀測與實際動作讀回、205 幀錄製及其五幀尾段、非固定 alpha、段邊界兩側讀取、缺檔、錄製證據與表格損毀、未知指紋與事件、相同 tick 的序號定序、半開區間邊界事件，以及排程漏幀的區間歸屬。

## 程式規範審查

獨立的規範審查未發現違反既有書面規範的項目。重複的觀測儲存配置定義已抽出為 `observation_contract`。審查也發現排程漏幀被歸入錯誤區間；目前已明確記錄受影響的時間範圍，並加入迴歸測試。後續複查確認兩項修正皆已完成。

## 規格符合性審查

獨立的規格審查發現啟動時可能重複取樣輸入或讀到舊輸入，且缺少事件的穩定排序。插件現在只在每個完成 `VFInput.OnUpdate` 的畫面幀記錄一次輸入，並等待該次取樣後才擷取畫面。編譯器依 ticks 與 sequence number 穩定排序，同時保留錄製證據的原始位元組。後續複查確認修正有效，且未在這些變更中發現其他待修正項目。

尚未完成的規格驗收：目前沒有使用這個 C# 插件完成新的實機錄製。合成測試通過，不能證明完整 UI 與游標擷取、遊戲實際輸入對應，或 Unity 停止錄製後銜接背景處理程序的流程已通過驗證。

## 實機驗證交接

已審查的 Release DLL 與設定檔已部署至遊戲安裝位置的 BepInEx 目錄。部署備份位於 `runs/deployment-20260908-090825`。初始設定未核准任何執行環境指紋，因此第一次按 F8 只會產生候選指紋，並拒絕開始錄製。

下一步請啟動 DSP、載入基準場景，再按一次 F8。將 `runs/live/runtime-candidate.json` 與已安裝的二進位檔案及設定逐一核對，只核准相符的指紋。接著錄製至少 15 秒，涵蓋 UI 操作、游標移動與 Digit1。核對新產生的四檔錄製證據、資料集讀回、輸出檔案校驗碼與遊戲紀錄，並將該次結果補入本報告後，才能宣稱此 Issue 已完成。

完整的連續回合生命週期、終止觀測、故障恢復與清理留待後續工作票處理。目前編譯器保留錄製事件與實際動作；任務與 reward 標籤，以及 10 Hz 模型視圖，尚未包含在這次初步整合中。

## 2026-09-09：F8 指紋檢查的空路徑修正

使用者首次按 F8 時，`Runtime()` 呼叫 `HashFile(assembly.Location)`，發生 `ArgumentException: Path is empty`。BepInEx 紀錄顯示 `UnityEngine.CoreModule` 經過啟動修補；[BepInEx 5.4.23.5 原始碼](https://github.com/BepInEx/BepInEx/blob/v5.4.23.5/BepInEx.Preloader/Patching/AssemblyPatcher.cs)會將修補後的組件載入記憶體。[Microsoft 文件](https://learn.microsoft.com/en-us/dotnet/api/system.reflection.assembly.location?view=netframework-4.8.1)說明，從位元組陣列載入的組件，其 `Assembly.Location` 為空字串。

已用 `Assembly.Load(byte[])` 重現同一空路徑錯誤。修正後，所有組件指紋都經由 `HashAssembly`：有 `Location` 時沿用原路徑，沒有時使用 BepInEx 提供的 Managed／core 目錄或插件的 `Info.Location`。讀取前核對來源的組件完整身分；缺檔、身分不符或未知遊戲雜湊仍然拒絕。指紋代表磁碟來源檔案，不宣稱是執行中已修補程式碼的雜湊。

可重跑的檢查：

```powershell
dotnet build tests/RuntimeFingerprint/RuntimeFingerprint.csproj
& tests/RuntimeFingerprint/bin/Debug/net472/RuntimeFingerprint.exe 'E:\Steam\steamapps\common\Dyson Sphere Program\DSPGAME_Data\Managed\UnityEngine.CoreModule.dll'
```

結果：記憶體載入、磁碟載入、缺檔拒絕、身分不符拒絕，以及實際 `UnityEngine.CoreModule.dll` 的來源雜湊檢查皆通過。13 項整合測試全部通過，耗時 22.93 秒；Release net472 建置零警告、零錯誤。獨立的規範與規格審查均未發現新增待修正項目。

修正提交為 `49c947a`，已重新建置並部署，備份位於 `runs/deployment-20260909-004010`。已部署 DLL SHA-256 為 `ac59770ed9790d123f92cd052e79f458a89468a7752cba3499a6fc5e98a1f88b`，指紋設定仍未核准。

最初的重現程式未捕捉例外，曾彈出 Windows 應用程式錯誤視窗；測試入口已改為捕捉例外、輸出原因並回傳非零結束碼。遊戲內 F8 及新的實機錄製仍待重試，不能以這次離線檢查宣稱實機驗收通過。
