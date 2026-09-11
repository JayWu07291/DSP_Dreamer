# Issue #18 模型視圖驗證

## 契約與前置證據

本票依 #12、#5、#10 的時間與動作決議實作。#14 的[驗收報告](issue-14.md)及[受控故障結果](issue-14-controlled-tests.md)已核對，涵蓋回合、重試、final observation 與有效前綴，未把關閉狀態直接當作 gate 證據。

#14 實作期間使用者追加 Space／E，README 與 #14 結案留言已修訂 #12 的 v2／18 維設定。本票沿用 `action_catalog_v3` 共 20 維，前 18 維順序不變，Space／E 位於 18／19。Digit1 位於 1、scan code=0x02、Unity Alpha1；數字鍵盤不映射為 Digit1。

## 驗收對照

| 條件 | 實作與檢查 |
| --- | --- |
| 20→10 Hz 原始時間聚合 | `open_model_view` 合併兩個相鄰區間，從 events.parquet 原始 samples 重算；保留起訖 held、fraction、counts、雙向 wheel、delta 與 sample 引用 |
| 短 click、閾值與 ambiguous | 10 ms click 保留 active；無 down 的 50% held active、49% inactive；兩個各自合法的 click 合併後標 ambiguous 並排除 sequence |
| 模型動作 | 固定 v3 順序；delta 合計後乘 20.0；mu-law maxval=10、binsize=2、mu=5；121 mouse × 3 wheel 全部編解碼往返與唯一 no-op 檢查 |
| 禁止與未支援輸入 | 六種禁止配對、六種合法組合、右 modifier、Mouse3、CapsLock、F8、未知鍵與數字鍵盤均有檢查；水平 wheel 抵銷仍 unsupported，原始事件保留 |
| RGB 與隔離 | compiled uint8 HWC 完整 sRGB；模型 float32 CHW [0,1]，未裁縮補邊；模型 inputs 與監督 targets、原始事件及來源分開 |
| 任務與邊界 | 保留原區間 task 切換時間，完成向量取所有完成，scalar 取視窗起始 task；半開邊界事件不重複計算；跨回合、gap、unknown-control 後綴與 ambiguous 不進 sequence |
| masks 與尾段 | 實際視窗與 padding 使用 valid_mask，burn-in 另外遮 loss_mask；不足兩個區間的尾段不假裝成 10 Hz 樣本，來源與 final observation 索引保留 |
| 儲存與拒載 | `/4` 保存 action codec、Zarr 原始 metadata、dtype／shape／chunk／shard、Parquet Arrow schema／實際 row groups／column codec、來源及 checksums；loader 重新驗證實際輸入聚合與事件引用 |
| 舊 artifact | 舊 schema／catalog 拒絕直接載入；v2 原始 evidence 重新編譯至新 artifact，保存 source_catalog／source_artifact_id；共用契約驗證拒絕舊 17 維 checkpoint 描述 |

## 自動化檢查

`tests/test_model_view.py` 包含模型視圖整合案例、動作編解碼與損壞資料拒載。透過正式 synthetic recording → FFV1 四檔 → Zarr／Parquet → 模型視圖完成驗證，沒有以 mock 代替資料路徑。

可重跑指令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_view.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
```

本票未新增遊戲端掛點或控制注入。合成資料驗證不代表已測量實機 10 Hz 閉迴路 deadline、長程 loader 記憶體或模型訓練品質；這些仍由後續工作驗收。尚無正式 checkpoint loader，後續訓練器須呼叫共用 `validate_action_contract`，本票不宣稱已完成模型載入器。
