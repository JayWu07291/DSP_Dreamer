# DSP Dreamer

Issue [#13](https://github.com/JayWu07291/DSP_Dreamer/issues/13) 建立第一條單回合錄製流程。Windows Unity 插件記錄人工輸入與完整畫面；Python 入口驗證並發布四檔錄製證據，編譯相鄰觀測與實際動作，再讀回轉移資料集。

## 環境設定

使用 Python 3.12，並以已安裝遊戲的組件作為編譯參考。在虛擬環境安裝依賴：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy==2.2.6 zarr==3.1.2 pyarrow==21.0.0 pytest==8.4.2 mypy==1.18.2
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj
```

插件固定使用 net472、Windows x64 Unity Mono、BepInEx 5.4.23.5 及其內建 HarmonyX 2.9.0。若遊戲安裝位置不同，請設定 MSBuild 的 `DSPRoot` 屬性。遊戲、Unity 與 BepInEx 組件只供編譯參考，不隨插件封裝。

FFmpeg 執行檔必須符合 SHA-256 `04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00`，即 #11 選定的 FFmpeg 6.1.1。編碼器透過可逆的 BGRA 通道轉換保留 RGBA，固定使用 FFV1 level 3、coder 1、context 0、GOP 1、slice CRC、四個 slices 與四個 threads。

## 錄製短回合

1. 結束 DSP，執行 `tools/deploy-recorder.ps1`。腳本會建置 Release、備份此錄製器既有的 DLL 與設定檔，再部署專案 DLL；執行環境指紋的核准欄位保持空白。
2. 啟動 DSP、載入預定的基準場景，再按 **F8**。錄製器會寫出 `runs/live/runtime-candidate.json`，並在指紋核准前拒絕錄製。請核對遊戲與 Unity 版本、二進位雜湊、輸入設定雜湊、畫面尺寸與 graphics API。插件與驗證器皆固定檢查支援的 Assembly-CSharp 雜湊。
3. 將 `BepInEx/config/tw.jaywu.dspdreamer.recorder.cfg` 中的 `ApprovedFingerprint` 設為已核對候選檔案的 SHA-256。插件會在下次開始錄製時重讀設定，不必重啟遊戲。若重建插件後雜湊改變，必須重新核對指紋。
4. 按 **F8** 開始錄製，操作至少 15 秒，涵蓋移動、Digit1、UI 面板與游標移動，再按 **F8** 停止。不要同時按住 Ctrl，避免觸發舊原型的快捷鍵。
5. 停止後，`.source` 旁會產生同名的 `.evidence` 與 `.dataset` 目錄。完成訊息為 `Recording, compilation, and readback completed`，寫入 `BepInEx/LogOutput.log`；仍須使用下方的驗證與讀回指令確認產物，不能只憑訊息判定成功。請保留遊戲紀錄與輸出目錄作為實機驗收證據。

擷取使用 12 個可重用緩衝區與有界寫入佇列，編碼器在擷取計時開始前完成準備。輸入在 `VFInput.OnUpdate` 後取樣，畫面透過 `WaitForEndOfFrame` 擷取，包含 UI 與合成的 DSP 游標紋理。每次要求都在 GPU 回呼前固定 ticks、序號、capture ID、Unity frame、game tick 與游標資訊；寫入程序依要求順序處理回呼結果。

按 F8、失去焦點、世界卸載或達到 30 分鐘時，錄製器會停止。擷取或寫入故障會保留來源檔案，且不發布完成標記；故障後請重新啟動 DSP。錄製過程不注入控制。完整生命週期、最終終止觀測、故障前綴恢復與來源清理留待後續工作票處理。

## 驗證、編譯與讀回

合成來源與實機來源使用相同指令處理，來源 metadata 會明確區分兩者。合成證據不能替代實機驗收。

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer finish --source runs/example.source --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer verify --source runs/example.source.evidence --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer compile --source runs/example.source.evidence --out runs/recompiled --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer inspect --source runs/example.source.dataset
```

發布流程先產生 `recording.mkv`、`frames.ndjson`、`events.ndjson`，最後原子發布 `manifest.json`。流程會完整解碼來源各段與合併影片，比較每幀 RGBA SHA-256 與 ordinal，以 seek 檢查每個段邊界兩側，並核對事件位元組；發布後再次檢查檔案。輸出目錄必須是新目錄，重試不能覆寫既有產物。

編譯器只接受已驗證的四檔錄製證據。動作區間為 `[requested_ticks_t, requested_ticks_next)`，事件依 `(ticks, sequence_number)` 排序。資料保留按住狀態、按住時間比例、按下與放開次數、observed delta／wheel 總和及原始取樣引用。不支援、有歧義、禁止的動作，以及漏幀區間，皆標為無效。Digit1 位於 `action_catalog_v2` 的 index 1，完整順序包含 18 個控制；不使用 Unity enum 數值代替硬體 scan code。

RGB 以 uint8 HWC 格式存入 Zarr v3，每個 chunk 一幀，使用 Blosc/Zstd 壓縮。Parquet 表使用 Zstd，每個 row group 最多 1,024 列。RGB 只存一次，相鄰觀測透過索引引用。檔案校驗碼、陣列配置、來源 ID 與工具版本都會在原子發布 `COMPLETED` 前保存；載入器先檢查檔案清單與校驗碼，再回傳資料。

```python
from dsp_dreamer import open_dataset

dataset = open_dataset("runs/example.source.dataset")
transition = dataset[0]
rgb = transition["observation"]
next_rgb = transition["next_observation"]
actual_action = transition["action"]
source_identity = transition["source"]
```

這個最小編譯器尚未產生任務、reward、終止標籤或 10 Hz 模型視圖，但會保存所有錄製事件，供後續編譯器使用。目前 metadata 載入記憶體，畫面則串流解碼。長時間錄製的記憶體使用量、完整恢復與訓練門檻需另行驗收。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore
```

公開介面測試涵蓋回呼亂序、200 幀分段、短尾段、非固定 alpha、段邊界 seek、相同 tick 的定序、半開區間事件、校驗碼錯誤拒絕，以及未知指紋與事件拒絕。測試使用 `tests/test_roundtrip.py` 指定路徑下的固定版本 FFmpeg。

游標合成程式改編自 `codex/prototype-issue-11-lossless` 分支中的 #4 原型，其他正式程式與原型分開實作，既有原型錄製保持不變。

新實機錄製與合成資料的最小整合驗收已通過，結果與限制見[Issue #13 驗證報告](docs/validation/issue-13.md)。`numcodecs` 的棄用警告目前會因 stderr 轉送方式而顯示為 `Error`；請以完整檔案驗證與讀回結果判斷資料是否可用。
