# DSP 錄製與閉迴路控制原型

這是 [issue #4](https://github.com/JayWu07291/DSP_Dreamer/issues/4)「製作同步 DSP 錄製與閉迴路控制原型」的拋棄式量測工具。它要回答一個問題：在目標電腦與目前 DSP 版本上，能否用明確的時間對齊契約，從 DSP 原生 1280×720、60 FPS 畫面下採樣成 640×360 RGB 資料，同時記錄 DSP 實際讀到的鍵鼠狀態、遊戲 tick、任務事件與注入動作，而且掉幀率低於 1%。10 Hz 用於完整流程驗證，20 Hz 與 30 Hz 用於壓力測試。

它不是正式錄製器。請勿把這個資料格式直接當成訓練資料契約。

## 時間對齊契約候選

所有事件使用同一個 `Stopwatch` 單調時鐘。

1. 外部動作取得 `action_id` 與 `requested_ticks`，再交給 `SendInput`。
2. 下一個 `VFInput.OnUpdate` postfix 記錄 DSP 實際讀到的鍵鼠狀態。若該樣本看到注入內容，它會記錄相同 `action_id`。
3. 同一 rendered frame 的 `WaitForEndOfFrame` 建立 RGB 擷取要求，固定保存要求當下的 `unity_frame`、`game_tick` 與待對齊的 `action_id`。
4. GPU callback 只補上 `completed_ticks`。它不得改寫要求當下的 frame、tick 或 action 身分。
5. 物品進入背包、指定面板開關、研究佇列、手作、手採、建造與登陸艙拆除事件保存發生當下的 `unity_frame` 與 `game_tick`。錄製開始時另存一份已開啟面板快照。資料載入器日後可把 `action_id` 對到同 rendered frame 結束時的 RGB 與 task label，形成 `observation_t, action_t, next_state_t`。

這個原型故意同時保存要求時間與完成時間。GPU callback 的完成順序不是資料時間順序。

## 執行

先關閉 DSP。從 repository root 執行：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 deploy
```

接著啟動 DSP。先在顯示設定選擇視窗化 1280×720、60 FPS，再載入基準場景。1280×720 是 DSP 原生支援的 16:9 解析度。原型先把完整畫面擷取到原生尺寸 RenderTexture，再用 GPU bilinear scaling 下採樣成模型輸入使用的 640×360。來源畫面若不是 16:9，原型會拒絕開始，避免拉伸影像。

畫面左上角會顯示狀態。

- `Ctrl+F8` 開始或停止擷取。預設 10 分鐘後自動停止。
- 錄製期間至少按三次 `Ctrl+F9`。每次會送出 100 ms 的 W 與 16 px 相對滑鼠移動，用來量 action-to-observation latency。
- 依序拆除登陸艙、開啟再關閉科技樹、加入研究佇列、手作並完成一項物品、完成一項科技、手動採礦，再放置至少一棟建築。這是事件涵蓋率 smoke test。
- `Ctrl+Shift+F11` 是緊急停止。它會先送出 W key-up。原型不使用 `F12`，因為 Steam 會攔截它做截圖。

錄製開始後，狀態面板會消失，避免污染 RGB 資料。停止擷取後，面板會重新出現並顯示結果。

結果位於 `BepInEx/plugins/DSPDreamerCaptureProbe/runs/<UTC>/`：

- `frames.rgba`：依 `capture_written.file_offset` 排列的 640×360 RGBA frame。
- `events.ndjson`：輸入樣本、擷取要求、寫入結果、任務事件與注入對齊資料。
- `summary.json`：來源解析度、顯示模式、實測 rendered FPS、掉幀原因、有效 Hz、寫入量與注入延遲。

顯示最近一次摘要：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 show-latest
```

這個命令也會列出錄製開始時的面板快照，以及 `task_event` 的總數與內容，包括物品取得、面板開關、科技樹開啟、研究排隊、手作排隊與完成、科技完成、手採產出、建造、一般拆除與登陸艙拆除。摘要把科技、配方、物品、建築、礦脈與植被 ID 和當次遊戲語言的名稱放在同一欄，方便人工核對。名稱也會寫入 `events.ndjson`，不必在離線檢查時載入 LDB。行星 ID 與名稱不記錄。

`item_acquired` 是沒有其他來源事件的背包狀態事件。錄製器會延後一個 game tick 寫入；若同 tick、item ID 與數量已有 `manual_mining_yield` 或 `craft_completed`，就不把 `item_acquired` 寫進 NDJSON。`summary.json` 的 `suppressed_item_acquisition_duplicates` 記錄寫入前刪除的數量。`show-latest` 仍會合併舊版 run 的重疊列，新版 run 的合併數應為零。

面板事件只追蹤 `UITechTree`、`UIReplicatorWindow`、`UIInventoryWindow` 與 `UIMechaWindow`。Unity instance ID 只在單次 run 內有效，所以白名單使用型別名稱，不固定 `#419754` 這類數值。

事件名稱與成功判定如下：

| `name` | 記錄時機 |
| --- | --- |
| `landing_capsule_dismantled` | `protoId 9999` 的登陸艙植被確實被移除 |
| `tech_enqueued` | `EnqueueTech` 後該科技的排隊數增加 |
| `craft_enqueued` | `MechaForge.AddTask` 回傳成功的工作 |
| `craft_completed` | 手作工作進入交付階段 |
| `tech_unlocked` | 遊戲送出科技解鎖事件 |
| `manual_mining_yield` | `PlayerAction_Mine` 登記實際產出 |
| `factory_build` | 工廠送出完成建造事件 |
| `item_acquired` | 沒有採礦或手作來源事件的物品實際進入玩家背包，保存 item ID、數量與增產點數 |
| `panel_opened` | 面板的 `active` 狀態從 false 變成 true，保存型別與 run 內 instance ID |
| `panel_closed` | 面板的 `active` 狀態從 true 變成 false，保存型別與 run 內 instance ID |

`panel_state_snapshot` 不是 task event。它在每次錄製開始時列出當下所有已開啟面板，之後可依 `panel_opened` 與 `panel_closed` 重建任一時間點的 UI 狀態。

把最近一次結果的第一幀轉成上下方向不同的兩張 PNG：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 export-frame
```

打開 `first-frame-native.png` 與 `first-frame-flipped.png`。記下方向正確的版本，並確認紅、綠、藍色沒有互換。

匯出適合人工檢查的事件畫面：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 export-event-frames
```

命令會選取每次科技樹開啟後 0.5 秒、科技樹關閉後的第一幀，以及可用的 episode 結束前與新 episode 開始後畫面，輸出 PNG 和 `event-frames.json` 索引。用這些畫面確認完整世界視野、科技樹、游標、方向與色彩，並確認錄製模組狀態面板沒有入鏡。指定舊 run 時可加上 `-RunDirectory '<run 路徑>'`；`show-latest`、`export-frame` 與下方的驗證命令也接受相同參數。

Probe 0.1.10 會在擷取要求當下保存游標位置、顯示狀態與 DSP cursor index。Unity 的 `ScreenCapture` 不包含 `Cursor.SetCursor` 交給視窗系統繪製的游標，所以 GPU frame 回讀後，probe 會把 DSP 當下的 cursor texture 和 hotspot 合成進 640×360 RGBA frame；若貼圖無法讀取，就改用固定黑白箭頭。`capture_written` 會記錄 `cursor_composited`、位置、合成像素數與貼圖來源，`summary.json` 則提供可見、已合成與 fallback frame 數量。事件 PNG 仍需人工確認游標位置正確。

建立逐幀 transition 並驗證時間對齊：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 verify-alignment
```

每一列 `alignment-manifest.ndjson` 都是一個相鄰 frame pair。區間採半開定義 `[observation.requested_ticks, next_observation.requested_ticks)`：區間內 DSP 實際讀到的 `input_sample` 是 `action_input_samples`，注入回讀是 `observed_injected_actions`，任務事件是 `next_state_events`，episode 邊界是 `episode_events`。`alignment-summary.json` 會檢查 capture 時間嚴格遞增、raw frame offset 有效，以及 task/action event 都有後續 observation；`alignment_verdict` 只在這些條件全部成立時通過。

若同一次錄製包含 `episode_end`、之後的 `episode_begin`，而且重新進入世界後仍能收到 task event，`world_reset_verdict` 會是 `pass`；沒有進行世界重載時是 `not_tested`。這兩個工具的完整 episode 與輸入對齊需要 probe 0.1.9 或更新版本，舊 run 會回報需要重錄，而不會猜測缺少的單調時間。

## 判定門檻

下列條件全部成立時，`metrics_verdict` 才是 `pass`：

- 至少錄製 60 秒。
- 總掉幀率低於 1%。總掉幀分成排程錯過、沒有空閒 GPU slot、GPU readback 錯誤與 writer backpressure。
- 有效寫入率至少是設定 Hz 的 95%。
- GPU readback 與 writer backpressure 都是零。
- 上表十種必要 task event 都至少記錄一次；`summary.json` 的 `missing_task_event_kinds` 必須是空字串。
- 至少做過三次注入，而且每個注入都在 100 ms 內由 `VFInput.OnUpdate` 觀察到。

數值門檻通過後，整體 `verdict` 仍是 `metrics_pass_visual_pending`。正式結論需要人工確認 frame 包含完整世界視野、科技樹 UI 與游標，不包含錄製模組狀態面板，且上下方向與 RGBA channel 正確。先跑 10 Hz。人工確認通過後，把 `BepInEx/config/tw.jaywu.dspdreamer.capture-probe.cfg` 的 `CaptureHz` 改成 20，再跑一次壓力測試。

## 原型結論

原型已於 2026-09-01 完成驗證。這個分支保留實作、驗證工具與量測方法，作為 issue #4 的原始證據；它不會直接合併為正式錄製器，也不定義正式訓練資料格式。

| 頻率 | 錄製時間 | 寫入幀數 | 有效頻率 | 掉幀率 | 對齊 | 用途 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 10 Hz | 137.180 秒 | 1364/1371 | 9.9431 Hz | 0.5106% | pass | 完整事件、世界重載與流程驗證 |
| 20 Hz | 69.473 秒 | 1385/1386 | 19.9358 Hz | 0.0722% | pass | 建議的預設錄製頻率 |
| 30 Hz | 61.981 秒 | 1811/1819 | 29.2185 Hz | 0.4398% | pass | 需要較密時間解析度時使用 |

人工與自動驗證結果：

- 完整畫面會以正確方向與色彩下採樣，不會裁切；錄製狀態面板不會進入資料。
- DSP 黃色游標會合成到影像中，位置與記錄座標一致；20 Hz 與 30 Hz 測試均未使用 fallback 游標。
- 十種必要 task event、物品取得去重、四個指定面板的狀態轉移，以及世界重載後重新綁定均已通過。
- `export-event-frames` 與 `verify-alignment` 可重建事件畫面及逐幀 transition；action-to-observation 延遲低於 100 ms。
- 20 Hz 與 30 Hz 都通過掉幀率、有效寫入率、GPU readback 與 writer backpressure 門檻。20 Hz 測試的整體 `metrics_verdict` 只因該次沒有執行 `factory_build` 而顯示 fail，效能門檻本身通過。

因此，原型證實目前 DSP 版本與目標電腦可同步取得 RGB、輸入、遊戲 tick、任務事件與 next-state label，也可進行閉迴路輸入注入。正式實作若沿用這些結果，應重新定義穩定的資料契約與維護邊界，不應直接依賴本原型的 NDJSON schema。
