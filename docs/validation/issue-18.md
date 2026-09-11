# Issue #18 模型視圖驗證

2026-09-11：109 項自動化測試及雙軸審查通過後，再以兩份既有實機錄製完成離線端到端驗收。完整流程與跨回合資料均通過，本票模型視圖範圍已完成。正式 checkpoint 恢復、實機控制 deadline 及長程資源 gate 仍由後續工作驗收。

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

審查補強了 COMPLETED 發布前驗證、gap 重算、unknown-control 後綴拒載及 lifecycle targets 重算。模型視圖與生命週期針對性回歸共 51 項通過。mypy 檢查 13 個原始碼檔案無問題。

2026-09-11 最終完整 pytest 共 109 項通過，耗時 124.19 秒。JUnit 結果保存在本機 `tmp/issue18-accepted.xml`。

可重跑指令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_model_view.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
```

本票未新增遊戲端掛點或控制注入。資料驗證不代表已測量實機 10 Hz 閉迴路 deadline、長程 loader 記憶體或模型訓練品質；這些仍由後續工作驗收。尚無正式 checkpoint loader，#25 的 action encoder／模型載入與 #28 的 checkpoint 恢復須呼叫共用 `validate_action_contract`，並驗證 v1／17 維、v2／18 維、控制順序與 codec 不符時拒載，以及 v3 正常恢復。本票已驗證共用拒絕函式，不宣稱已完成模型載入器。

## 實機 evidence 的離線驗收

使用 #16 已通過的完整產線流程，以及 #15 已通過的重試／跨回合錄製。`tools/verify-model-view.py` 先確認舊 dataset 拒載，再透過正式 compiler 完整解碼、驗證四檔並建立新的 `/4` dataset；loader 重新核對全部 stored RGB checksums、原始事件與動作、lifecycle、codec 及索引。原始影片、events、frames、manifest 的前後 SHA-256 完全一致，舊 dataset 的 COMPLETED 亦未變，沒有重標或覆寫舊 artifact。

| 項目 | #16 完整流程 | #15 重試／跨回合 |
| --- | ---: | ---: |
| 原始 RGB 幀 | 7,204 | 3,345 |
| 原始事件 | 31,605 | 15,835 |
| 20 Hz 轉移 | 7,203 | 3,344 |
| 10 Hz 模型視窗 | 3,602 | 1,673 |
| 可訓練視窗 | 3,597 | 1,667 |
| 合法 64-step 起點 | 3,303 | 1,456 |
| 保留 task 切換 | 16 | 11 |
| 獨立解碼逐像素抽查 RGB 幀 | 56 | 43 |
| Digit1 實際 down 次數 | 2 | 2 |

所有視窗均核對起訖 held、時間加權 fraction、down/up counts、delta、雙向 wheel 與 sample/event 引用，不能以已量化類別平均替代。真實滑鼠與鍵盤的逐鍵次數保存在 JSON。完整流程的 16 個微任務及 7 個里程碑各完成一次，合併後沒有丟失或重複。

完整流程排除 5 個視窗，涵蓋 2 個 ambiguous、2 個 gap 與 1 個不足兩段的尾窗；重試資料排除 6 個視窗，涵蓋 ambiguous、gap、F9／F8 未支援控制及不完整視窗。分類可重疊。成功回合最後的 50 ms 單段仍保存完成與 final observation 來源，但不冒充完整 10 Hz 樣本，loss／bootstrap 為 0。

所有 4,759 個合法 64-step 起點均核對不跨 episode／attempt 或無效範圍。另實際載入每份資料首尾的 64-step batch，確認 burn-in masks；9 個有效區間結尾的 batch 均在邊界停止並 padding。task 切換及無效邊界周邊共 99 個 RGB 幀由原影片獨立解碼，與模型 float32 CHW 全尺寸逐像素相等，inputs 沒有具特權狀態。

來源、衍生 artifact ID、檔案 checksums、排除計數、節點與切換时间、抽查索引均保存於 [完整流程結果](issue-18-full-flow-live.json)及[重試結果](issue-18-retry-live.json)。大型影片與 dataset 保留於本機 `runs/live/`，沒有上傳 GitHub。Space／E 在這兩份錄製沒有 down，相關順序與投影由本票整合 fixtures 及 #14 既有實機證據支持，不宣稱此次實機重播新增了這兩鍵的正例。

可重跑指令，dataset 與 report 必須指定尚不存在的新路徑：

```powershell
.\.venv\Scripts\python.exe tools/verify-model-view.py --evidence runs/live/0eec2f28-174d-4f1a-88d4-c2819e3b01c7.source.evidence --dataset runs/live/issue18-full-flow-v4 --ffmpeg E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe --report docs/validation/issue-18-full-flow-live.json
.\.venv\Scripts\python.exe tools/verify-model-view.py --evidence runs/live/9013a109-5dcb-4f89-b808-c1234d23b823.source.evidence --dataset runs/live/issue18-retry-v4 --ffmpeg E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe --report docs/validation/issue-18-retry-live.json
.\.venv\Scripts\python.exe -m mypy dsp_dreamer tools/verify-model-view.py
```

兩次執行均回報 `status=passed`，含驗證腳本的 mypy 共 14 檔通過。此次只新增驗證工具及證據，正式 runtime 維持 `9006db3`，沿用該版 109 項完整測試結果。

## Standards

以 `ec83811a824450d5ca2c80edbb783c688fbe7000` 為基準，由獨立 agent 審查 AGENTS.md、domain 規則、CONTEXT.md、Ponytail 及 code-review smell baseline，沒有需修改的問題。

## Spec

獨立 agent 發現一項缺口：loader 沒有重算 lifecycle validity、terminal／truncation／bootstrap，重新封存後可能接受偽標為有效的無效尾段。現已保存 next episode／attempt 身分，重用 `transition_lifecycle` 驗證回合身分、邊界與 targets，並新增 human_intervention 尾段偽造後必須拒載的整合測試。未發現範圍擴張。

原審查 agent 已複核確認修正。Standards 共 0 項，Spec 共 1 項已解決，兩軸均無未解決問題。
