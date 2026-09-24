# Issue #22：資料與人工標註凍結完成

Jay 回覆「127 題的兩項都正確」。本次只提升這 127 題的範圍與第 15 步狀態，保留原分類、原話、來源和時間。既有 114 列正式候選未變；242 段作答中有 241 段完整候選，P085 原本的不確定答覆仍保留。

| 分類 | 完整候選 | 固定抽樣 | 尚需人工補標 |
| --- | ---: | ---: | ---: |
| 移動／視角 | 50 | 50 | 0 |
| UI | 63 | 50 | 0 |
| 建造／物品 | 64 | 50 | 0 |
| 等待 | 64 | 50 | 0 |
| 合計 | 241 | 200 | 0 |

本階段不需要再錄製或標記影片。未抽中的 41 段完整候選、P085、不曾處理的候選及全部人工原文均保留；沒有為了模型表現更換名單。

## 凍結結果

- 原有重建名單維持 200 張，17 個 task_id 各至少 10 張，與先前封存名單完全一致。
- 15 個人工確認的關鍵項目納入正式 `dsp-evaluation-annotations/1`：物品／數字 10、游標 2、配方 1、連接 2，分布於 7 張圖。另保留 5 張圖上的 8 個 UI 範圍，涵蓋五類 UI。沒有捏造其他圖片的人工確認。
- 預測從全部 241 列正式候選依 seed 2201 與完整 row hash 固定選出四類各 50 段，再沿同 task、同類排序循環指定打亂 donor，固定 generation seed。每段都是同一回合連續 79 個合法 10 Hz 視窗。
- Train baseline、24 份來源、split 和原 TrainingIndex 均未改動。資料覆蓋仍為 train／validation／offline-test 各微任務至少 20／3／3 個合法 active 正例。
- 分類者、確認來源及凍結時間已封存。正式 annotation 綁定含預測名單的新 evaluation inputs；另保存與舊輸入包的逐來源對應，沒有改寫舊包。

### 主要身分

| artifact | ID |
| --- | --- |
| protocol v2 | `40167e30d83bab5b60b19498ac45380899cd942d8f87fc347db37cae893a9e42` |
| 原 TrainingIndex | `7301b78d7d5caaa63b2f600201c9c41d0890123bfe47f1d264cc1e7aa3b2ba21` |
| data freeze | `57d8fbadf60c6a00ece0500dc5f3c14abc5e1ac546aed2edc11c88fd6390775f` |

其餘完整身分及 checksum 見 [凍結收據](evaluation-data-freeze-20260924.json)。本機輸出目錄為 `runs/catalog-v4/corpus-integration-20260921/evaluation-freeze-20260924`，包含正式輸入包、annotations、候選封存紀錄、動作對照證據、來源版本及 data freeze。

## 對照的可比數

下表只檢查前五步量化動作是否不同，不是模型誤差、成績或通過門檻。

| 分類，原分母均為 50 | no-op | 同類打亂 | 複製末圖 |
| --- | ---: | ---: | ---: |
| 移動／視角 | 50 | 48 | 50 |
| UI | 49 | 46 | 49 |
| 建造／物品 | 47 | 48 | 47 |
| 等待，另報 | 27 | 33 | 27 |

無動作差異的配對仍保留在名單與證據中，實際評分時依協定列證據不足。尚未取得模型誤差，baseline error=0 的數量與最終可比成績保持待驗證，不能把上述數字當成品質 gate 通過。

## 讀取範圍與可重現性

這次重驗 24 份小型 COMPLETED／dataset metadata，沿用 9 月 21 日完整資料驗證的內容 hash。只讀三份 validation 來源的 transitions／events 表，使用既有 ModelView 和封存 `prepare_evaluation` 產生名單、donor、動作差異和 seed。傳入抽樣器的是暫時的 validation 投影，不另發佈 TrainingIndex；投影產生的空 train baseline 丟棄，正式包沿用原有已封存 train baseline。重新抽出的重建名單必須與舊包逐列相同才可繼續。

沒有重開全 Dataset、讀取 RGB chunks、重建語料、複製媒體或重新編碼。資料凍結綁定原完整驗證所指的 immutable bytes；往後載入實際 dataset 時，仍須由正常 loader 驗 checksum，這次 metadata 檢查不能代替內容驗證。

[凍結工具](freeze-reviewed-evaluation.py)的輕量核對命令：

```powershell
.venv/Scripts/python.exe docs/validation/freeze-reviewed-evaluation.py --check
```

檢查確認 127 列精確提升、原 114 列不變、241 完整候選、四類各 50、整列 hash 排序、同 task／category 循環 donor、15 步動作、第 5 步差異、generation seed、原 200 張圖與 train baseline 不變、15 個關鍵項目和 8 個 UI 範圍、seal 與 provenance。此命令只讀已保存的收據及小型結果，不重讀動作表或影像。

## 複核

Standards 與 Spec 各由獨立代理以 `237c7e5` 為基準複核，均通過。Standards 無硬性違規或可操作的結構問題；Spec 確認 §41–43 的抽樣、人工來源、凍結及未授權訓練邊界。兩者也各自執行輕量 `--check` 通過。`mypy dsp_dreamer` 的 18 個來源檔通過。

完整 pytest **158 項通過，170.75 秒**。第一次執行因 Windows 舊暫存目錄 `pytest-of-jay07` 的存取權限，在測試初始化階段出錯；改用新的專案內暫存目錄後全數通過，未修改產品程式或測試：

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short --basetemp tmp/evaluation-freeze-tests-20260924 -p no:cacheprovider
```

`--basetemp` 應使用新的空目錄；上列保留本次實際命令。

## 後續邊界

資料與標註已凍結，模型品質仍為 pending；沒有啟動或授權訓練，也沒有查看 offline-test 圖片或模型結果。下一階段需要模型、checkpoint、固定配方與模型評分；offline-test 揭露仍必須先有依順序綁定的 recipe freeze。

40 個保留 trial 的 10 development／30 final、seed、偏航及 manifest 隔離驗證通過。其輸入設定 hash 與目前示範環境的既有差異，仍須在實際遊戲試驗前處理，不能把本次資料凍結當成 trial 已可直接執行。這不需要再補這一輪的人工標註。
