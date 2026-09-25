# 單回合工程 runner

Issue #29 的 runner 從正式錄製器取得含 UI、游標的 RGB，載入已銜接 tokenizer／dynamics 的第二或第三階段工程 checkpoint，經 SendInput 控制 DSP。此入口只接受 `engineering_only` checkpoint，不授予正式候選資格；#34／#35 仍須核對模型 gate 與正式試驗身分。

## 使用方式

先以 `tools/deploy-recorder.ps1` 部署，核對新的 runtime fingerprint，並以 F6 控制探針重新錄製、編譯及發布校正。DLL 變更後不能直接沿用舊校正。保留原 DLL、設定與校正檔，校正產物另存新位置。

在 `tw.jaywu.dspdreamer.recorder.cfg` 加入：

```ini
[Policy]
Checkpoint = E:\GitHub\DSP_Dreamer\runs\issue-29\controlled-checkpoint-1000\agent.pt
Device = cuda
DelayMs = 0
```

在已載入的遊戲中按 F5。工作程序先載入、暖機並核對完整動作 codec，才啟動錄製、重新載入基準存檔與施加 manifest 的擾動。第一個動作為 no-op。F8 停止並釋放控制；暖機期間 F8 取消啟動。回合成功、死亡、30 分鐘 timeout、人工介入或系統故障也會結束並自動封存。卡住不會自行提早判敗。

`DelayMs = 120` 可在工程推理後加入 120 ms 延遲，以重現 deadline miss。只用於工程驗證；完成後恢復為 0。人工介入偵測包含實體輸入與其他程序的注入，錄製器自己的 SendInput 使用固定來源標記。此標記用於區分本機來源，不是安全驗證機制。

## 時間、模型輸入與輸出

錄製維持 20 Hz，控制以第一張有效觀測的 request ticks 建立 10 Hz 時鐘。每個時槽使用最新可用的觀測，Unity 更新時若已超過 100 ms 而未能提交新動作，就釋放並送 no-op，遲到的回覆不會重播。deadline 檢查與 Python 推理分開，最多一個 pipe exchange 在執行；沒有無界推理佇列。連續五次 miss 會結束無效嘗試。若 Unity 主執行緒本身停頓，釋放須等其恢復；這類試驗會因延遲超標判無效，並不具備即時作業系統的硬性期限保證。

Policy 的公開輸入只有 RGB、DSP 實際低階動作及 17 維 one-hot。實際動作以正式 compiler 的半開區間聚合與 codec 產生；不以送出的 request 代替，也不修補 ambiguous／unsupported 動作。任務來自正式 v4 判定與排程。最多保留 64 步，提示切換保留歷史，回合身分改變時重設。工作程序只收到時間、識別碼、seed、task ID、RGB 和低階輸入樣本，不取得遊戲內部狀態。

目前重新編碼完整的 64 步歷史，尚未加入推理快取。Windows 上不同歷史長度會累積大量 CUDA 閒置配置，因此每次推理前釋放閒置快取，保留模型與完整歷史。短工程試驗不能證明正式模型在 30 分鐘同開條件下的延遲或資源 gate。

每個 `runner_step` 保存 capture request、inference start/end、提交 request 與 request ID。編譯後按 DSP input 樣本核對 observed ticks、注入、按鍵釋放及滑鼠校正，再計算 p95 ≤ 80 ms、p99 ≤ 100 ms、miss ≤ 1%、無連續五次 miss。percentile 使用線性插值，缺測保持 null，miss 納入分母。

同一個 DSP 取樣間隔內連續送出的 no-op 與釋放，共用下一個實際空按鍵樣本。這能確認整組操作後的空狀態，不能分辨是哪一次釋放生效。若第一次釋放後已有樣本顯示按鍵仍 held，後續重試的空樣本不能用來替第一次背書。

Unity Mono 的 Stopwatch 與 Windows QPC 原點不同。插件在每次啟動工作程序前配對兩個時鐘，確認頻率一致，再讓 Python 將推理時間換算至錄製器時鐘；使用的 offset 留在 runner metadata。checkpoint 及其 tokenizer 來源檔也須能由執行 DSP 的 Windows 帳號讀取；pytest 的私有暫存目錄可能不具備這項權限。

鍵盤與滑鼠監看使用專用執行緒處理 Windows 訊息，避免 Unity 在 SendInput 中等待自己的 hook 回呼。回呼只更新人為輸入旗標，不讀取 Unity 狀態。這符合 [Windows 對低階 hook 訊息迴圈的要求](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)。動作與釋放另記錄 `submission_completed_ticks`，可分開核對 SendInput 耗時。

最終證據維持 `recording.mkv`、`events.ndjson`、`frames.ndjson`、`manifest.json` 四檔；衍生資料集與 `<source>.result.json` 放在旁邊，不追加到證據目錄。結果分開保存 outcome、validity、checkpoint checksum、來源 checksum 與全部時序。合法死亡或 timeout 不會自行成為系統錯誤；人工介入、注入失敗與系統超標則使結果無效。工程錄製標記 diagnostic mode，使轉移資料不會誤入正式訓練。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_runner.py tests/test_control.py tests/test_control_guards.py tests/test_lifecycle.py -q
.venv/Scripts/python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --configuration Release
```
