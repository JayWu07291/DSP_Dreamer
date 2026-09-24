# 正式資料位置

2026-09-24 整理後，後續訓練與評估要用的資料集中到 `data/`。這是同磁碟區的目錄搬移，沒有重編譯、重建索引、重新抽樣或修改已凍結的 JSON。

| 路徑 | 內容 |
| --- | --- |
| `data/datasets/<artifact_id>/` | 24 份正式轉移資料集，包含 RGB、transitions、events、metadata 與 COMPLETED |
| `data/training-index.json` | 已凍結的來源、split、合法起點及覆蓋統計 |
| `data/prediction-candidates.json` | 241 列完整人工候選，正式使用其中 200 段 |
| `data/evaluation/` | 正式評估輸入、annotations、provenance、動作對照與 data freeze |
| `data/runtime/calibration.json` | 目前核准的校正檔，遊戲設定已同步更新路徑 |

[data-catalog.json](data-catalog.json)是目前位置表。每份資料保留 `artifact_id`、`split`、原路徑 `previous_path` 與來源 COMPLETED 身分；新的位置表不取代原 TrainingIndex 或 data freeze。

這次整理的搬移紀錄、清單與一次性腳本已移至[封存資料夾](archive.md)下的 `maintenance-20260924/`，本機不再保留 `data/maintenance/`。

實際需要載入完整語料時，可使用現有介面：

```python
import json
from pathlib import Path
from dsp_dreamer.training_index import TrainingIndex

catalog = json.loads(Path("docs/data-catalog.json").read_text(encoding="utf-8"))
index = TrainingIndex.open(
    catalog["training_index"],
    [source["path"] for source in catalog["sources"]],
)
```

這個 loader 會完整核對來源，適合實際開始使用資料時執行。查看位置、標註進度或封存狀態不需要重跑它。

凍結檔案中的歷史路徑及工具路徑保留原樣，避免改變其內容身分。它們描述凍結當時的環境；目前載入位置以 `data-catalog.json` 為準。歷史人工原文、頁面與一次性凍結工具保存在[封存](archive.md)中。

資料與人工標註已完成，模型品質、recipe freeze、offline-test 揭露與正式試驗仍待後續工作。Issue #22 的逐條核對見[完成紀錄](issue-22-completion.md)。
