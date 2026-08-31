# DSP 錄製與閉迴路控制原型

這是 issue「製作同步 DSP 錄製與閉迴路控制原型」的拋棄式量測工具。它要回答一個問題：在目標電腦與目前 DSP 版本上，能否用明確的時間對齊契約，從 DSP 原生 1280×720、60 FPS 畫面下採樣成 640×360、10 Hz RGB 資料，同時記錄 DSP 實際讀到的鍵鼠狀態、遊戲 tick、任務事件與注入動作，而且掉幀率低於 1%。

它不是正式錄製器。請勿把這個資料格式直接當成訓練資料契約。

## 時間對齊契約候選

所有事件使用同一個 `Stopwatch` 單調時鐘。

1. 外部動作取得 `action_id` 與 `requested_ticks`，再交給 `SendInput`。
2. 下一個 `VFInput.OnUpdate` postfix 記錄 DSP 實際讀到的鍵鼠狀態。若該樣本看到注入內容，它會記錄相同 `action_id`。
3. 同一 rendered frame 的 `WaitForEndOfFrame` 建立 RGB 擷取要求，固定保存要求當下的 `unity_frame`、`game_tick` 與待對齊的 `action_id`。
4. GPU callback 只補上 `completed_ticks`。它不得改寫要求當下的 frame、tick 或 action 身分。
5. 科技、建造與拆除事件保存事件發生當下的 `unity_frame` 與 `game_tick`。資料載入器日後可把 `action_id` 對到同 rendered frame 結束時的 RGB 與 task label，形成 `observation_t, action_t, next_state_t`。

這個原型故意同時保存要求時間與完成時間。GPU callback 的完成順序不是資料時間順序。

## 執行

先關閉 DSP。從 repository root 執行：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 deploy
```

接著啟動 DSP。先在顯示設定選擇視窗化 1280×720、60 FPS，再載入基準場景。1280×720 是 DSP 原生支援的 16:9 解析度，原型會把它下採樣成模型輸入使用的 640×360。來源畫面若不是 16:9，原型會拒絕開始，避免拉伸影像。

畫面左上角會顯示狀態。

- `Ctrl+F8` 開始或停止擷取。預設 10 分鐘後自動停止。
- 錄製期間至少按三次 `Ctrl+F9`。每次會送出 100 ms 的 W 與 16 px 相對滑鼠移動，用來量 action-to-observation latency。
- 開啟科技樹，移動、點擊、拖曳、滾輪操作，並在可行時觸發一個科技或建造事件。
- `Ctrl+Shift+F11` 是緊急停止。它會先送出 W key-up。原型不使用 `F12`，因為 Steam 會攔截它做截圖。

結果位於 `BepInEx/plugins/DSPDreamerCaptureProbe/runs/<UTC>/`：

- `frames.rgba`：依 `capture_written.file_offset` 排列的 640×360 RGBA frame。
- `events.ndjson`：輸入樣本、擷取要求、寫入結果、任務事件與注入對齊資料。
- `summary.json`：來源解析度、顯示模式、實測 rendered FPS、掉幀原因、有效 Hz、寫入量與注入延遲。

顯示最近一次摘要：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 show-latest
```

把最近一次結果的第一幀轉成上下方向不同的兩張 PNG：

```powershell
.\prototypes\issue-4-recorder\probe.ps1 export-frame
```

打開 `first-frame-native.png` 與 `first-frame-flipped.png`。記下方向正確的版本，並確認紅、綠、藍色沒有互換。

## 判定門檻

一次結果只有在下列條件全部成立時才是 `pass`：

- 至少錄製 60 秒。
- 總掉幀率低於 1%。總掉幀分成排程錯過、沒有空閒 GPU slot、GPU readback 錯誤與 writer backpressure。
- 有效寫入率至少是設定 Hz 的 95%。
- GPU readback 與 writer backpressure 都是零。
- 至少做過三次注入，而且每個注入都在 100 ms 內由 `VFInput.OnUpdate` 觀察到。

正式結論仍需人工確認原始 frame 包含世界、科技樹 UI、游標與 overlay，且上下方向與 RGBA channel 正確。先跑 10 Hz。通過後，把 `BepInEx/config/tw.jaywu.dspdreamer.capture-probe.cfg` 的 `CaptureHz` 改成 20，再跑一次壓力測試。
