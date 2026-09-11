# DSP Dreamer

Windows Unity 插件記錄人工輸入與完整畫面；Python 入口驗證並發布四檔錄製證據，編譯相鄰觀測與實際動作，再讀回轉移資料集。#14 加入基準重設、同一工作階段的回合邊界與終止標籤。

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

目前錄製器要求先完成 #20 控制校正。首次部署請先依[人工實機操作步驟](docs/validation/issue-20.md)執行 F6 探針、正式編譯讀回及校正核准，再使用以下 F8 人工錄製流程。尚未執行的實機測試不視為通過。

1. 結束 DSP，執行 `tools/deploy-recorder.ps1`。腳本會建置 Release、備份此錄製器既有的 DLL 與設定檔，再部署專案 DLL；執行環境指紋的核准欄位保持空白。
2. 啟動 DSP、載入預定的基準場景，再按 **F8**。錄製器會寫出 `runs/live/runtime-candidate.json`，並在指紋核准前拒絕錄製。請核對遊戲與 Unity 版本、二進位雜湊、輸入設定雜湊、畫面尺寸與 graphics API。插件與驗證器皆固定檢查支援的 Assembly-CSharp 雜湊。
3. 將 `BepInEx/config/tw.jaywu.dspdreamer.recorder.cfg` 中的 `ApprovedFingerprint` 設為已核對候選檔案的 SHA-256。插件會在下次開始錄製時重讀設定，不必重啟遊戲。若重建插件後雜湊改變，必須重新核對指紋。
4. 確認基準存檔為登陸後尚未操作的 `Starting Save`。按 **F8** 開始錄製時會重新載入它；操作至少 15 秒，涵蓋移動、Digit1、UI 面板與游標移動。**F9** 先結束目前回合，再從同一基準重試；**F8** 結束錄製並發布。不要同時按住 Ctrl，避免觸發舊原型的快捷鍵。
5. 停止後，`.source` 旁會產生同名的 `.evidence` 與 `.dataset` 目錄。完成訊息為 `Recording, compilation, and readback completed`，寫入 `BepInEx/LogOutput.log`；仍須使用下方的驗證與讀回指令確認產物，不能只憑訊息判定成功。請保留遊戲紀錄與輸出目錄作為實機驗收證據。

擷取使用 12 個可重用緩衝區與有界寫入佇列，編碼器在擷取計時開始前完成準備。輸入在 `VFInput.OnUpdate` 後取樣，畫面透過 `WaitForEndOfFrame` 擷取，包含 UI 與合成的 DSP 游標紋理。每次要求都在 GPU 回呼前固定 ticks、序號、capture ID、Unity frame、game tick 與游標資訊；寫入程序依要求順序處理回呼結果。

`[Trial]` 設定包含 `BaselineSave`、`MechaSeed`（預設 17）、`CameraSeed`（29）與 `PolicySeed`（41）。開始時凍結基準存檔 SHA-256、世界種子、設定及獨立偏航擾動；機甲與相機各從 ±15 度均勻取樣。F9 保留 trial manifest 與 split group，每次重試產生新的 attempt／episode ID，並重新訂閱科技與工廠事件。基準檔案或設定不符時拒絕重試。

回合從擾動後第一張可控制且有效的 RGB 要求時間起算，30 分鐘使用單調時鐘，包含 UI 與暫停，不把載入時間算入。死亡與超時自動結束回合；任務模組可呼叫 `EndEpisode("success")` 或 `EndEpisode("unrecoverable")`，控制模組可傳入 `reason: "human_intervention"` 等有效性原因。人工示範本身不被當成人工介入故障，也沒有新增卡住提前終止規則。

停止、重設、失焦、世界卸載及故障會釋放鍵鼠控制。回合結束時最多等待兩秒取得 final observation；缺失則標為 `incomplete`。回合結束後按 F9 重試或 F8 發布工作階段。GPU 擷取故障可保留已驗證的合法前綴；writer／佇列致命故障不發布成功標記，並盡力留下 `INCOMPLETE.json` 診斷，之後須重啟 DSP。每完成 200 幀會保存帶 checksum 的檢查點；恢復只使用完整核對的檢查點，`INCOMPLETE.json` 不能授權恢復或編譯。

## 驗證、編譯與讀回

合成來源與實機來源使用相同指令處理，來源 metadata 會明確區分兩者。合成證據不能替代實機驗收。

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer finish --source runs/example.source --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer verify --source runs/example.source.evidence --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer compile --source runs/example.source.evidence --out runs/recompiled --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer inspect --source runs/example.source.dataset
```

發布流程先產生 `recording.mkv`、`frames.ndjson`、`events.ndjson`，最後原子發布 `manifest.json`。流程會完整解碼來源各段與合併影片，比較每幀 RGBA SHA-256 與 ordinal，以 seek 檢查每個段邊界兩側，並核對事件位元組；發布後再次檢查檔案。`finish` 預設完成核對及來源清理後才編譯。來源與 evidence 必須位於同一磁碟區，資料檔與 manifest 皆以不覆寫的 rename 發布。

發布收據保存本次來源、工作目錄、清單與 checksum。部分發布可用原本的 `finish` 指令重試；已完成 evidence 與 dataset 會先驗證再沿用。清理中斷可重試，僅刪除解析後仍位於本次工作目錄且 checksum 相符的檔案。其他錄製、無關檔案和失敗嘗試留下的未核對工作目錄都保留。Python `publish` 預設保留來源，可明確傳入 `cleanup=True` 啟用清理。若 compiler 中斷留下未完成 dataset，請用 `compile --out` 指向新目錄。

來源受損或程序被終止時，使用新的 evidence 路徑恢復：

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer recover --source runs/example.source --out runs/recovered.evidence --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer compile --source runs/recovered.evidence --out runs/recovered.dataset --ffmpeg 'PATH\ffmpeg.exe'
```

恢復從最新可驗證檢查點取連續前綴，完整核對 sidecar 位元組前綴、來源段 checksum、RGBA 解碼、索引與進度重播，再產生新 artifact ID。原始來源與故障尾端保留；manifest 和 dataset 的 `recovery.recording_complete=false` 明示它不是完整錄製，記錄排除起點與無法確定的尾端。缺 final observation 的回合標為 `incomplete`，尾端不提供 bootstrap。相同恢復指令可重試已發布產物。舊來源若沒有 sealed 檢查點，不能憑診斷檔推測恢復。

容量預檢在已有來源之外，預留兩份本次檔案容量及 1 GiB 餘裕；恢復另多預留一份副本。compiler 以未壓縮 RGB、每 capture 小時 2 GiB 表格及 1 GiB scratch 估算。空間不足或來源變更會停止流程。受控程序終止測試不代表斷電、OS 或磁碟故障保證，詳細結果見[封存恢復驗證](docs/validation/issue-17.md)。

編譯器只接受已驗證的四檔錄製證據。動作區間為 `[requested_ticks_t, requested_ticks_next)`，事件依 `(ticks, sequence_number)` 排序。資料保留按住狀態、按住時間比例、按下與放開次數、observed delta／wheel 總和及原始取樣引用。不支援、有歧義、禁止的動作，以及漏幀區間，皆標為無效。2026-09-10 使用者新增 Space（跳躍）及 E（單獨開關背包），動作契約升為 `action_catalog_v3`，共 20 維。原本 18 個 index 保持不變，Space 追加在 index 18、E 在 index 19，Digit1 仍在 index 1；不使用 Unity enum 數值代替硬體 scan code。

這項使用者決議修訂 #12 的 v2／18 維設定。後續模型視圖、action encoder 與 policy head 應使用 v3／20 維，尚未實作的模型模組不宣稱已更新。完整控制順序以 `dsp_dreamer/contract.py` 的 `CONTROLS` 為準，並存入每份 dataset metadata 供 loader 核對。

RGB 以 uint8 HWC 格式存入 Zarr v3，每個 chunk 一幀，使用 Blosc/Zstd 壓縮。Parquet 表使用 Zstd，每個 row group 最多 1,024 列。RGB 只存一次，相鄰觀測透過索引引用。檔案校驗碼、陣列配置、來源 ID 與工具版本都會在原子發布 `COMPLETED` 前保存；載入器先檢查檔案清單與校驗碼，再回傳資料。

資料集格式為 `dsp-transitions/4`，catalog 為 `action_catalog_v3`。舊 `/1`、`/2`、`/3` 或 catalog v2 資料集必須從原始 evidence 重編譯到新目錄。raw evidence v2／v3 皆可驗證，重編譯從原始輸入產生新版動作並保存 `source_catalog`。缺 lifecycle 的舊 evidence 不推測終止結果，bootstrap mask 為 0；缺進度事實時 `progress_available=false`，不推測任務或 reward。

```python
from dsp_dreamer import open_dataset

dataset = open_dataset("runs/example.source.dataset")
transition = dataset[0]
rgb = transition["observation"]
next_rgb = transition["next_observation"]
actual_action = transition["action"]
source_identity = transition["source"]
legal_starts = dataset.sequence_starts(64)
```

轉移包含 `episode_outcome`、`validity_status`、原因、`is_terminal`、`truncation` 與 `bootstrap_mask`。success／death／unrecoverable 的終止轉移不 bootstrap；timeout 可 bootstrap；無效或 incomplete 尾端不 bootstrap。缺 next observation 的動作不產生轉移。`sequence_starts` 只回傳不跨回合、gap 或無效範圍的固定長度起點；未知控制之後的同回合範圍不納入訓練。

進度提供固定 17 維任務條件、16 維 reward_vector 與 7 維背景里程碑，並核對遊戲端與離線重播結果。新版 `progress_version=3` 依目前供電、固定配方、採礦機／傳送帶／分揀器連接與各機器實際產出判定完整產線。允許保留或補入人工材料；只有人工餵料、缺少可自行運作的上游連接不算成功。舊版 1、2 保留各自原有重播語意。完整契約、已測範圍與實機驗收結果見[完整產線驗證](docs/validation/issue-16.md)，前置實機證據見[早期進度驗證](docs/validation/issue-15.md)。長程記憶體與訓練門檻仍需後續實作及驗收。#14 已測範圍見[生命週期驗證報告](docs/validation/issue-14.md)。

## 10 Hz 模型視圖

```python
from dsp_dreamer import open_model_view

view = open_model_view("runs/example.source.dataset")
window = view[0]
batch = view.sequence(start=0, length=64, burn_in=8)
inputs = batch["inputs"]
valid_mask, loss_mask = batch["valid_mask"], batch["loss_mask"]
```

loader 合併同回合的兩個相鄰 capture 區間，沿用原始 request ticks 與半開區間規則。它從原始 samples 重算 held、fraction、down/up、delta 與雙向 wheel，再將合計滑鼠 delta 各軸乘 20.0，以 mu-law 量化為 121 類。mouse 類別為 `x_bin*11+y_bin`，wheel 負／零／正對應 0／1／2；全零 binary、mouse=60、wheel=1 是唯一 no-op。共用 `dsp_dreamer.actions` 提供編解碼與 catalog／checkpoint 契約驗證。

`inputs` 只包含完整 RGB float32 CHW、17 維任務條件和模型動作；reward、next observation 與 bootstrap 放在 `targets`。逐窗結果另外保存原始動作、sample／event 引用、區間內 task 切換與來源索引。合併 reward_vector 保存所有完成，scalar reward 只取視窗起始 task。`view.metadata` 保存 loader、codec、來源 COMPLETED checksum 與可重現的模型視圖 ID，可隨訓練紀錄保存。

重複 click 或非法組合可能在合併後才出現，這些視窗保留證據但不供 BC／dynamics。不足兩個區間的尾段同樣不供訓練，保留 final observation 的來源。`sequence_starts` 只列出完整合法起點；`sequence` 遇無效區間或回合邊界便停止並補零。`valid_mask` 區分實際樣本與 padding，`loss_mask` 另排除 burn-in。不要將逐窗的無效資料直接送入模型，其 `inputs.action` 為 null。驗證範圍見 [#18 報告](docs/validation/issue-18.md)。

## 固定 split、片段與覆蓋

用途登錄檔採 `dsp-split-registry/1`，每列指定 `manifest_id`、`split_group_id`、`purpose`，用途限 `demonstration`、`development`、`final`。範例見 [#19 登錄檔](docs/validation/issue-19-registry.json)。錄製前先登錄並凍結用途，納入全部保留 manifests；沒有登錄或身分不符的資料會拒收。現有錄製沒有用途欄位，因此由登錄檔補上，不修改原始 evidence。

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer index --source runs/live/issue18-full-flow-v4 runs/live/issue18-retry-v4 --registry docs/validation/issue-19-registry.json --length 64 --out runs/training-index.json
```

`split_group_id` 的 UTF-8 SHA-256 以無號整數取模 100，0–79 為 train、80–89 為 validation、90–99 為 offline-test。同 manifest 重試與衍生資料不重抽；任一 development／final 登錄會排除整組。每份錄製只選一個正式衍生 dataset，重複錄製或回合會拒收，避免重複計數。更換 sequence 長度不改 split。抽樣 seed 只決定起點抽樣，不影響 split。

輸出包含三個 split 的統計、16 個微任務各自的 20／3／3 門檻與缺口，以及逐來源的 `uniform`、`relevant`、`progress` 全部起點。`uniform` 是完整合法 sequence 的全集，`relevant` 含至少一個節點完成；`progress` 含原始 `progress_fact` 且沒有完成，不包含單純 `progress_observation` 擷取快照。progress 只供分析，不自動解讀為 reward 或採用另一套進度判定器。

完整回合時數取已驗證的回合起訖時間；`legal_hours` 只加總可訓練的 10 Hz 視窗，`legal_prefix_hours` 是其中無效／不完整回合的合法部分，遇 gap 分開計算，不重複加總重疊 sequence。active 啟用及非 active 完成按有效模型視窗計數，背景里程碑另併入 split 的非 active 完成總數。`active_reward_episodes` 只計至少一個合法 sequence 能包含的 scalar reward 正例，按不同回合去重；`live_active_reward_episodes` 再限實機來源，合成 fixtures 不補足正式門檻。非 active 完成與等待都不增加 scalar reward 正例。

```python
from dsp_dreamer.training_index import TrainingIndex

dataset_paths = ["runs/live/issue18-full-flow-v4", "runs/live/issue18-retry-v4"]
index = TrainingIndex.open("runs/training-index.json", dataset_paths)
samples = index.sample_stage_two("validation", 2, seed=19)  # 檢查現有資料；正式訓練使用通過 gate 的 train。
for sample in samples:
    batch = index.sequence(sample, burn_in=1)
    # 分別供 dynamics、policy、reward loss 使用。
    masks = [batch[f"{name}_loss_mask"] for name in ("dynamics", "policy", "reward")]
```

偶數 batch 精確一半從全部合法起點均勻、有放回抽樣，另一半從 relevant 起點均勻、有放回抽樣。兩個抽樣池可抽到同一起點，loss 用途仍各自獨立。空抽樣池直接拒絕，不改成其他比例。三種 loss masks 都排除 burn-in；索引只容許完整 sequence，padding 不會進入抽樣。回傳資料仍含模型視圖既有的通用 `loss_mask`，訓練器必須使用對應的三種專用 mask。索引工具可在覆蓋不足時執行以規劃補錄，後續訓練仍須檢查 `coverage_gate_passed`。

輸出原子發布且不覆寫，`artifact_id` 是除該欄位外、依 key 排序 JSON 的 SHA-256；來源包含 dataset、recording、模型視圖版本及 COMPLETED／manifest checksum。`TrainingIndex.open` 重新核對來源並重建比對全部內容，拒絕損壞或與來源不符的索引。索引與完整模型視窗 metadata 目前放在記憶體；完整十小時資料的資源量測仍由 #21 驗證。

## 驗證

```powershell
dotnet restore tests/ProgressReplay/ProgressReplay.csproj
dotnet restore tests/ArchiveRecovery/ArchiveRecovery.csproj
dotnet restore tests/ControlReplay/ControlReplay.csproj
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore
```

公開介面測試涵蓋回呼亂序、200 幀分段、短尾段、非固定 alpha、段邊界 seek、相同 tick 的定序、半開區間事件、校驗碼錯誤拒絕，以及未知指紋與事件拒絕。測試使用 `tests/test_roundtrip.py` 指定路徑下的固定版本 FFmpeg。

游標合成程式改編自 `codex/prototype-issue-11-lossless` 分支中的 #4 原型，其他正式程式與原型分開實作，既有原型錄製保持不變。

新實機錄製與合成資料的最小整合驗收已通過，結果與限制見[Issue #13 驗證報告](docs/validation/issue-13.md)。`numcodecs` 的棄用警告目前會因 stderr 轉送方式而顯示為 `Error`；請以完整檔案驗證與讀回結果判斷資料是否可用。

## 受控故障測試

診斷模式預設關閉。測試部署使用 `tools/deploy-recorder.ps1 -Diagnostics`，或在開始錄製前設定 `[Diagnostics] Enabled = true`；模式在 F8 開始時固定，寫入來源 metadata。診斷錄製的所有轉移皆不供訓練。完整操作與核對方式見[受控測試步驟](docs/validation/issue-14-controlled-tests.md)。

| 快捷鍵 | 受控情境 |
| --- | --- |
| F10 | 回報 human_intervention，走正常 EndEpisode 與控制釋放 |
| Shift+F10 | 模擬一次 release 注入失敗，再立即實際重試 release；保留 injection_failure |
| F7 | 下一次 GPU readback callback 拋出測試例外，走 recorder_fault 與 final observation 收尾 |

故障皆標 `simulated=true`，不宣稱 Windows 或 GPU 自然發生故障；F12 保留給 Steam 截圖。測試完成後將 Diagnostics 關閉，再開始正式錄製。
