# Issue #15 早期進度驗證

## 範圍與狀態

依 #12、#2 與 #15 實作。#14 的六項驗收及受控故障證據已核對通過。動作沿用使用者修訂的 `action_catalog_v3`，錄製為 20 Hz；10 Hz 模型視圖由後續工作處理。

實作 `start_dismantle`、`queue_research`、`queue_crafting`、`fuel_mecha`、`mine_copper`、`place_iron_miner`、`place_copper_miner`，以及 `lander_done`、`electromagnetism_done`。其餘節點保留原 ID、依賴及優先順序，predicate 暫不成立，由 #16 接續。

目前完整測試 30 項通過，mypy 九檔無問題，Release 建置零警告、零錯誤。實機驗收待執行；合成 fixture 與舊原型不能替代本票實機驗收。

## 判定與時間契約

登陸艙開始拆除取自實際採集工作量；完成取自採集流程移除登陸艙。科技排隊比較完整佇列前五項；科技完成直接讀取解鎖事實，不從依賴推論。

成功加入製作佇列後，按本次請求批數乘以每批產量，累計 10 個磁線圈及 10 個電路板。製作、機甲燃料與親採銅礦只在拆完後成立。親採銅礦取 `TryAddItemToPackage` 實際入包數量，其他來源不計。

燃料基準拒絕背包、物流背包、手持、燃燒室內已有液氫燃料棒或已有建築的場景。原生物品沒有逐棒來源 ID，因此以非登陸艙取得量及工廠製造量的累計上界，核對燃燒室現存量，包含正在燃燒的一棒。只有已取得登陸艙燃料，且放入後現存量大於全部可能的外來燃料，才證明至少一棒來自登陸艙。同一外來燃料反覆取放不消耗這個上界。混合來源、回收入包可能使正例延後；來源無法證明時不猜測完成。

採礦機記錄礦脈、電網身分、遊戲傳入的供電比例及實際產量差值。錯礦種、沒有產出、電網為零或供電比例低於遊戲採集門檻 0.1，均不完成。礦脈快照到產量取樣依遊戲既有順序鎖定 veinPool，再鎖 production register，避免礦脈移除競爭及其他執行緒污染差值；實機效能仍待量測。

`progress_fact` 保存事實。每次擷取要求的 `progress_observation` 保存提示、23 個累計節點、上一提示對應的 scalar reward、16 維 reward_vector 及全部新完成 ID。即使擷取失敗也保留要求邊界，供離線重播提示切換。

排程只在觀測邊界前進。active 未完成不搶占；非 active 完成鎖定並跳過。等待 task ID 為 16，無 scalar reward。提示切換保留累計狀態，新回合才重設。完成事件的節點 ID 16–22 是背景里程碑，與等待 task ID 分屬不同欄位。

轉移的 `microtask_completed` 與 `milestone_completed` 是區間起點累計狀態；`node_completions` 與 `reward_vector` 是 `[start, end)` 新完成事件。scalar reward 只取起點 task_id 的 reward_vector 分量，跨回合歸零。

資料集為 `dsp-transitions/3`。loader 核對 ID、維度、one-hot、scalar reward 與完成事件一致性。舊 evidence 缺少事實時 `progress_available=false`，不推測完成。特權事實留在 evidence 與 events table，不加入 loader 的 RGB／動作輸入。

## 可重跑檢查

```powershell
dotnet restore tests/ProgressReplay/ProgressReplay.csproj
.\.venv\Scripts\python.exe -m pytest tests/test_progress.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore -c Release
```

`ProgressReplay` 直接編譯正式 C# 狀態機。fixture 經它產生遊戲端宣告，再走正式封存、Python compiler 與 loader。覆蓋非 active 完成、不搶占、多完成、邊界、等待、數量不足、其他來源、無效採礦機、重複產出、狀態逆轉、未實作後期科技、重試及重編譯一致性。修改宣告後即使重算 checksum 仍須拒絕。

## 實機操作

1. 關閉 DSP。Agent 建置、備份及部署新版，維持 Diagnostics 關閉。
2. 啟動 DSP，載入 `Starting Save`，按一次 F8 產生候選指紋。等 agent 核對核准後再按 F8，讓錄製器重載基準。
3. 開始拆登陸艙。拆除期間依序排入電磁學、自動化冶金、基礎物流系統、基礎製造、電磁矩陣五項科技。
4. 拆完後排入 10 個磁線圈及 10 個電路板，每項通常為五批。至少放一個液氫燃料棒進燃燒室，親採至少四個銅礦。
5. 等電磁學解鎖。建立鐵礦採礦機，先未供電停留約兩秒，再接有效供電，確認產出。另製作並建立銅礦採礦機、供電，確認產出。
6. 再等五秒。按 F9 重試；重載後開始拆登陸艙並重新排科技，等至少五秒，按 F8 結束。
7. 回報完成及看到的錯誤。Agent 完整解碼、核對 checksum、compiler／loader 讀回與逐回合提示／節點／reward，保存來源及限制。

固定優先序會先啟用 `supply_metallurgy`。其 predicate 屬 #16，本版提示會停在它；鐵／銅採礦機仍可在非 active 狀態完成，留下 reward_vector，scalar reward 為零。

## Standards

審查固定點為 `9be2d38554059dbd2ef8943284ea33ad1c13e684`，包含本票新增檔。沒有書面標準違規。三項判斷性意見為跨 C#／Python 的規則重複、遊戲數字 ID 的可讀性，以及只有一處呼叫的 `WithName` 轉接函式。轉接已移除；兩份 runtime 規則保留並由整合比對防止不同步，遊戲 ID 保持外部契約數值。

## Spec

審查找到兩項判定風險。採礦機在多執行緒下的礦脈快照可能變動，已改為依原生順序鎖定礦脈及產量資料。燃料只用登陸艙取得額度抵扣插入量，可能誤認其他來源，已改為以外來來源上界及燃燒室現存量證明來源，並加入重複取放反例。

規範軸原有三項判斷性意見，一項已修、兩項保留；規格軸原有兩項風險，均已修正。實機驗收仍待執行。
