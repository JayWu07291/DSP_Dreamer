# DSP 錄製與閉迴路控制原型

這是 issue「製作同步 DSP 錄製與閉迴路控制原型」的拋棄式量測工具。它要回答一個問題：在目標電腦與目前 DSP 版本上，能否用明確的時間對齊契約，從 DSP 原生 1280×720、60 FPS 畫面下採樣成 640×360、10 Hz RGB 資料，同時記錄 DSP 實際讀到的鍵鼠狀態、遊戲 tick、任務事件與注入動作，而且掉幀率低於 1%。

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

## 判定門檻

下列條件全部成立時，`metrics_verdict` 才是 `pass`：

- 至少錄製 60 秒。
- 總掉幀率低於 1%。總掉幀分成排程錯過、沒有空閒 GPU slot、GPU readback 錯誤與 writer backpressure。
- 有效寫入率至少是設定 Hz 的 95%。
- GPU readback 與 writer backpressure 都是零。
- 上表十種必要 task event 都至少記錄一次；`summary.json` 的 `missing_task_event_kinds` 必須是空字串。
- 至少做過三次注入，而且每個注入都在 100 ms 內由 `VFInput.OnUpdate` 觀察到。

數值門檻通過後，整體 `verdict` 仍是 `metrics_pass_visual_pending`。正式結論需要人工確認 frame 包含完整世界視野、科技樹 UI 與游標，不包含錄製模組狀態面板，且上下方向與 RGBA channel 正確。先跑 10 Hz。人工確認通過後，把 `BepInEx/config/tw.jaywu.dspdreamer.capture-probe.cfg` 的 `CaptureHz` 改成 20，再跑一次壓力測試。
