# 移動確認與補充覆核

Jay 回覆「10 題的三項都正確」，已依上一頁的題目與提案保存原話、收件時間、分類、範圍及第 15 步狀態。確認 P231、P244、P276、P299、P311、P336、P347、P372、P388、P392；沒有把這句話套用到其他題目。

| 分類 | 已確認分類 | 要求 | 分類缺口 |
| --- | ---: | ---: | ---: |
| 移動／視角 | 23 | 50 | 27 |
| UI | 63 | 50 | 0 |
| 建造／物品 | 64 | 50 | 0 |
| 等待 | 64 | 50 | 0 |

合計 215 段有人工作答／確認，其中 214 段已分類，P085 待判定。10 段三項全部確認，另 205 段的既有紀錄逐列保留，64 段 waiting 範圍草稿也保持未確認。這些數字不是最終 200 段抽樣已完成。

## 已完成的代理工作

從 frozen index 的三份 live validation 來源，只讀 `dataset.json`、`transitions.parquet`、`events.parquet`，對照原先已驗證的 COMPLETED 摘要及檔案雜湊。沿用 ModelView 檢查 frozen metadata、64 步合法起點；79 步合法起點數分別為 3034、3243、5970。同時得到原 400 題的 task_id，將上述 10 段編成 `dsp-prediction-candidates/1` 片段。尚未執行最終 200 段選取或凍結新 evaluation inputs。

以原輸入活動安排檢視順序：前 5 步至少 3 步有 WASD、滾輪或中鍵鏡頭拖曳，再用既有 sampling seed 對來源／起點／task_id 排序。947 個搜尋結果完整保留，先抽出 48 個未與原 400 題重複、彼此未重疊的 1.5 秒補充視窗。此規則只安排代理檢視順序，不產生分類或排除標籤，也不變更最終依完整候選列雜湊抽樣的規則。

代理已看完 48 組起點／第 5／15 步原圖，再以原生 640×360 核對其中 27 組，填好 movement、全畫面範圍、第 15 步游標所指位置。其餘 21 組仍待處理，不能解讀為非 movement。全體 400 題原候選仍保留；沒有依模型輸出挑選資料。

這次讀取三份 validation 表格、143 個唯一 RGB chunk；各 chunk 在讀取前均核對原 COMPLETED checksum，zarr metadata 也經核對。沒有呼叫會讀遍 RGB 的完整 Dataset loader、掃描其他歷史批次、重建索引、修改來源、複製或重編影片。新增原圖 PNG 約 143 張；頁面用 hard link 共用它們和既有影片。

## 人工接手

開啟 [27 題集中覆核頁](http://127.0.0.1:8856/)，題號 M001 等以避免與原 P 題衝突。每題只核對分類、範圍和末幀游標狀態三項。全數符合可回覆「27 題的三項都正確」，有誤只列題號、項次與修正，不確定則保留不確定。無需補錄、填座標或重寫整段操作。

若 27 題全數通過，移動分類達 50／50，完整候選達 37 段。先前僅確認分類的其他片段，仍需由代理整理範圍與關鍵狀態，再集中交付人工核對。訓練尚未授權，最終候選抽樣及資料凍結均未完成。

## 來源與核對

- [10 題確認收據](movement-priority-01-confirmed-20260924.json)
- [補充來源收據](movement-supplement-source-01-prepared-20260924.json) 與 [擷取程式](prepare-movement-supplement.py)
- [27 題覆核頁收據](movement-supplement-review-01-prepared-20260924.json) 與 [頁面產生器](prepare-movement-supplement-review.py)
- [可重跑的檢查](check-movement-supplement.py)：`.venv/Scripts/python.exe docs/validation/check-movement-supplement.py`

檢查已通過：seal、檔案 checksum、原 205 列不變、10 列精確確認與 task_id 映射、48 組選取順序、三個原圖的步數對齊、27 列仍待確認、21 列保留、媒體 hard link。檢查不重新開啟來源 dataset 或 RGB archive。

完整測試 158 項通過（180.10 秒）；mypy 的 18 個來源檔案通過。瀏覽器已確認 27 部影片、81 張原圖，M001 實際播放後停在 135.700 秒（終點 135.65 秒），640×360、無影片錯誤，首組三張原圖正常載入。伺服器使用 8856；重啟命令為 `.venv/Scripts/python.exe tools/serve-annotation-workbench.py runs/catalog-v4/corpus-integration-20260921/movement-supplement-review-01 8856`。

## Standards

獨立複核：硬性違規 0、可行動的 Fowler smell 0。檢查通過，來源鏈、不可覆寫輸出與 hard link 一致；10 段人工確認和 27 段代理提案保持分開，既有答案及未處理候選保留。只讀三份 validation 表格與指定 chunks，沒有完整 Dataset loader 或語料重建。

## Spec

獨立複核：缺漏、範圍擴張或錯誤實作 0。第 5 步分類、原圖時間邊界與來源合法性一致；人工原話僅提升既有 10 列，新 27 列仍待確認。輸入活動只安排檢視順序，原候選、947 個搜尋結果及 21 列 deferred 保留，未套用於最終抽樣。P085、資料凍結和訓練授權狀態不變。

Standards 0 項、Spec 0 項發現。
