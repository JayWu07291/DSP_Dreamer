# 資料製作與模型品質評估協定 v2

本協定在補錄及查看模型結果前固定。契約來源為 [#12](https://github.com/JayWu07291/DSP_Dreamer/issues/12)、[#8 正式決議](https://github.com/JayWu07291/DSP_Dreamer/issues/8#issuecomment-5552509084)及 [#7 正式決議](https://github.com/JayWu07291/DSP_Dreamer/issues/7#issuecomment-5549118917)。依 2026-09-16 使用者確認的 B 建築模式操作，使用 action_catalog_v4，共 21 個 binary controls；20 Hz 錄製、10 Hz 模型視圖與控制、640×360 RGB、17 個 task_id、30 分鐘回合不變。

協定、工具、trial manifests 的內容 hash 收在 `evaluation-v2.json`。修改任何規則、實作、門檻、版本或標註格式，必須另建協定版本，保存舊版及變更原因，不得因模型未達標而放寬。本版沒有任何模型結果；人工標註仍為部分草稿，完整判讀待驗證。`pending` 是待驗證，`insufficient_evidence` 是證據不足，`failed` 是完成測量但未達門檻，只有完整必要證據均達標才能寫 `passed`。缺測用 null，不能填零或 true。產生協定或輸入包不授權訓練。


2026-09-16 修訂原因：第二批兩個正常示範因 B 不在舊 20 維控制清單而被排除。B 追加在 index 20，scan code=0x30，原 index 0–19 不變；X 仍在 index 13。v1 及其全部 checksum 綁定檔案保留。本版不修改 split、抽樣、門檻、標註格式、研究／產線 predicate 或任務排程。原始 evidence 可重編譯為新 artifact，重新判定輸入有效性；不直接取消舊失效標記，也不允許其他未知鍵。所有旧 dataset、草稿及結果保持原版本身分。

原 40 份保留 trial manifests 沿用，尚未執行；其輸入設定 hash 與目前示範環境不同，正式閉迴路試驗前仍須處理此差異。不能以本次 B 控制修訂宣稱它們已可直接執行。

## 資料與凍結順序

1. 補錄前固定本協定、評分及標註規則、seed、baseline 演算法、trial manifests。現有 #19 覆蓋 gate 未過，僅可執行資料檢查及補錄規劃。
2. 示範約 3 小時先檢查，其餘約 7 小時按缺正例、操作與恢復情境補錄；正常／恢復約 70／30 是人工工時。沿用固定世界及 UI、完整連續回合，不建立微任務存檔。
3. 補錄後凍結全部錄製、compiler／loader 版本、來源 checksum、registry、TrainingIndex 與 split。依 split_group_id 的 SHA-256 全部位元取模 100，0–79／80–89／90–99 對應 train／validation／offline-test。相同 manifest 重試、衍生片段不得跨 split；不得重抽補正例。40 份 development／final manifests 的整組均排除。新示範也不得重用其偏航及 RNG seeds。
4. 只用 train 建立 baseline；按本版抽樣規則固定 validation 名單。分類、區域、關鍵項目與排除原因在模型結果出現前凍結。人工尚未恢復時，保留不足名單與 pending，不能宣告實際 200 圖／200 序列或標註完成。
5. Offline-test 在配方凍結前只能驗證契約及標籤覆蓋計數，禁止計算或揭露模型分數、畫面判讀及閉迴路結果。依序封存 `dsp-evaluation-data-freeze/1` 與 `dsp-evaluation-recipe-freeze/1`，再由 `authorize_test_disclosure` 檢查內容連結和時間順序。資料凍結包含 protocol_id、index_id、evaluation_inputs_id、annotations_id、supplementation_complete=true、含時區 frozen_at；配方凍結包含 data_freeze_id、checkpoint_sha256、recipe_sha256、selection_split=validation+development、offline_test_seen=false、final_seen=false、frozen_at。所有識別均為內容 SHA-256。
6. 揭露後保存全部分數與版本，不回流調參、重跑挑選或修改門檻。契約修復需保留污染與失效紀錄，不能將原 test 當成新盲測。工具不能證明人在外部沒有看過結果，凍結紀錄必須如實保存；未來 evaluator 必須在讀取 test 預測前呼叫揭露檢查。

每個微任務需 20 train／3 validation／3 offline-test 不同回合的 active scalar reward 正例。非 active 完成、等待、重疊片段不得補數，合成資料不補實機門檻。完整有效回合數與時數、合法故障前綴時數、合法 sequence、active 啟用、正例回合、非 active 完成逐 split 報告，完整與前綴不重複計時。採用 TrainingIndex 的合法性、source lineage 與 gate，不重新發明 split。checksum、版本、時間、RGB／游標、動作、reward、gap／fault／未知控制不符即拒收。

## 重建抽樣與標註

候選是實機 validation 模型視圖中每個合法 10 Hz 視窗起始 RGB，按 artifact_id、model_index 去重。固定排序鍵為 SHA-256 的 `json.dumps([seed, row], sort_keys=True, allow_nan=False)` UTF-8 位元組；sampling seed=2201。每個 task_id 0–16 先取排序最前 10 圖，再從其餘全體候選取至 200。無放回，不用其他 task 填缺失 quota。名單綁定 index_id、source model_view 與 COMPLETED checksum。主要 UI 覆蓋由原圖標註確認；不足時記缺口，不能看重建結果後換圖。

標註 artifact 使用 `dsp-evaluation-annotations/1`，包含 protocol_id、evaluation_inputs_id、annotator、含時區 frozen_at、items。每個 item 必須含 sample_id、artifact_id、observation_index、type、box、expected、eligible、exclusion_reason；type 固定為 cursor、recipe、item_number、connection。sample_id 在包內唯一。box 為原生 RGB 半開整數 [x0,y0,x1,y1]。eligible=false 僅接受原圖無法辨識或該項目不存在的理由，必須在看重建前寫定。不能用模型圖挑選可辨識項目。

游標必須形狀可辨且中心落在原標中心 5 pixel 內；配方必須正確識別選中配方，不能只判有面板；物品／數字需物品身分及完整數字逐字相符；連接需端點、方向與連通狀態皆相符。每項只計全對／錯，不給部分分。每個樣本可有多個 item，各佔一個分母。四種類型各至少一個 eligible item；需涵蓋科技、背包、製造、建造及研究站 UI，缺類型／UI 覆蓋即證據不足。人工評估預設 pending。

判讀另存結果 artifact，引用 annotation_id、checkpoint hash，每項 correct=true/false/null、reviewer 與 evidence。分母為所有事先凍結 eligible items，未判讀不能從分母移除。整體正確／總數 ≥95%，四類各 ≥90%。另報排除數、缺判數及逐 task 結果。

全圖 MSE 在 sRGB float32 [0,1] 上對 RGB、pixel、frame 等權平均；UI MSE 只用原圖預標 UI 半開矩形聯集的 pixels，每張圖先算，再對有 UI 圖等權平均，列 pixel 數與圖數。LPIPS 固定[官方 PerceptualSimilarity](https://github.com/richzhang/PerceptualSimilarity) 的 [lpips 0.1.4](https://pypi.org/project/lpips/0.1.4/)、AlexNet、version=0.1、eval mode、spatial=false，輸入由 [0,1] 轉 [-1,1]，不 resize。執行環境與 AlexNet／LPIPS 權重檔 SHA-256 必須在模型評估前收進配方；未固定或套件不可用則待驗證，不換 metric。此票不安裝訓練依賴。

64／96-token 對照使用相同名單、標註、seed=2202、資料順序、loss 與 optimizer update 數。各至多 30 分鐘，測速後先固定雙方可完成的共同 updates；量測未完成則 updates=null、不能執行對照。納入編碼器 4 小時上限，本版仍採 64，不憑短程對照自動替換或宣稱收斂容量優勢。

## 動作條件預測

每個候選必須由同一回合連續 79 個合法 10 Hz 視窗構成，前 64 個是真實歷史，後 15 個是預測動作／目標。從 history 最後 next observation 起始自由預測，第 1／5／15 步比較對應 next observation；未來不餵真圖。提示可切換，保留其紀錄，分類 task_id 為第一個預測動作的 active task。

人工只看原始證據，將候選依主要可見操作分類為 movement 移動／視角、ui UI 操作、interaction 建造／物品互動、waiting 等待。混合操作以預先標定第 5 步受影響狀態決定主要類別；無法判定者列排除，不由按鍵猜 UI 語意。候選 artifact `dsp-prediction-candidates/1` 包含 protocol_id、index_id、samples，各列有 artifact_id、start、task_id、category、reviewed=true、evidence、regions、key_states。evidence 指向原始 capture／事件，regions 是原生 RGB 半開矩形清單，key_states 每項含 type、expected。分類者與凍結時間另存候選封存紀錄。完成分類後依相同 sampling seed 與 row hash 無放回每類取 50，缺額不重複取樣。候選只有分類及真實標籤，禁止帶預測結果選樣。

受影響區域依真實歷史及未來影格中，操作改變的游標、UI、物品、建築與連接的最小包圍矩形，四邊加 8 pixel，裁至 640×360；相機移動致全景改變時採全畫面。分離區域先取聯集的最小外框以避免重複像素；原始內容小於 64×64 時等量擴至至少 64×64 並限制邊界。LPIPS 不 resize，此一外框固定供所有對照和 1／5／15 步使用。等待組以全畫面及預標穩定狀態另報。

四個條件共用歷史、起點、generation_seed、推理設定與區域：正確 15 步動作；15 步唯一 no-op；同 task、同 category 的已選序列按排序循環取下一列完整 15 步動作，末列取首列；複製最後歷史觀測至全部未來步。Singleton 的打亂等於自身，列無動作差異。生成 seed 由 generation 基底 2203 和 artifact_id/start 的 SHA-256 前 8 hex 決定，三個生成條件重設至同一亂數狀態；copy-last 無生成亂數。

第 5 步每個前三類、每個 baseline 分別報完整配對明細。正確動作與 no-op／打亂在前 5 步的量化 action 序列至少一項不同才算有差異；copy-last 配對也要求前 5 步正確序列非全 no-op。若 baseline error=0 或無有效動作差異，該配對列證據不足及排除理由，不算改善。每項比較只用同一組配對先算 correct 平均與 baseline 平均，再算 `(baseline_mean-correct_mean)/baseline_mean`，必須 ≥10%。列原候選數、可比數、零誤差數、無差異數與實際分母；分母為零、缺任一類或必要比較則不能通過，不用 pooled 數字蓋過逐類失敗。

第 15 步依事前 key_states 判讀，全體正確／總數 ≥80%，前三類各 ≥70%，等待另報。判讀準則沿用四類關鍵項目，未判讀保留分母與 pending。全圖 MSE／LPIPS、第 1／5／15 步、等待、逐 task 與三個 baseline 的所有數字另列。上述是推理診斷，不代表重新訓練無動作模型的因果消融。

## Reward 與 policy

Reward 只在 validation 完整有效回合的全部合法連續 10 Hz transitions 評估，一個 transition 一次，不能使用 50% relevant 抽樣，也不能用故障前綴代替完整回合。預測期望 reward ≥0.5 為正；ground truth 為 active scalar reward。16 個微任務各列 N、實際正例、預測正例、TP／FP／FN／TN、precision=TP/(TP+FP)、recall=TP/(TP+FN)、正例基率=(TP+FN)/N，precision 與 recall 均 ≥80%。沒有實際正例或預測正例時相應值 null、證據不足，不能通過。PR-AUC 固定用非插值 average precision，相同 score 作同一 threshold，Σ(recall 增量×precision)，列定義，無正例為 null。

主要計數精確 transition 對齊。±1 個 100 ms 步的匹配只作延遲診斷，在同回合、同 active task 內依距離最小再依時間最早一對一匹配，不可跨提示；不得替代 gate。等待與非 active completion 且 scalar reward=0 的 transitions 分別報 N、FP，不能把同時 active reward=1 者當成應為零。

Policy 使用 validation 合法 relevant 64-step sequences 所涵蓋的 transitions 聯集，不重複加權重疊視窗，僅算當前步且不做 burn-in 抽樣。Binary 每個機率 ≥0.5，mouse／wheel 取 argmax，同值取最小 class。有正例 binary controls 逐一 F1=2TP/(2TP+FP+FN)，其等權 macro-F1 ≥0.60；21 控制皆列原始計數，無正例者明列排除，全部缺正例時證據不足。Digit1、Space、E、B 亦遵守相同規則。

Mouse ground truth !=60 與 wheel !=1 分別為非零子集，各 exact-class accuracy≥50%，各相對 train 的 task-conditioned baseline 高 ≥10 個百分點。Baseline 在每個 task 的全部合法 train transitions 逐一計類別頻數，mouse／wheel 各取眾數，同數取最小 class。不要只用 train 非零子集建 baseline，no-op 也列入 train 頻數；也不讀 validation／offline-test 建模。Baseline 與 policy 在完全相同非零子集配對，列 correct、baseline_correct、N 與 train 頻數／來源，某被測 task 無 train baseline 或子集空則證據不足。

另報按每 transition 平均的 joint action NLL，21 binary Bernoulli 加 mouse／wheel categorical 負 log 機率，零機率為 +infinity 而非暗中 clamp；no-op 比例、禁止組合率、逐 task 指標與分母。任一非有限 gate metric 或缺必要證據不能通過。

重建通過才進第一階段 dynamics；資料覆蓋、重建及動作預測通過才進第二階段；第二階段 dynamics、reward、policy 皆通過才進 imagination。第三階段候選也須通過相同離線檢查才進 development。任何人工依賴仍 pending 就停止相關階段，保留合格第二階段退路，不能將不合格模型稱為退路。

## 試驗 manifests、選模與報表

`evaluation-trials-v1.json` 固定 10 development 與 30 final 完整 trial manifests。使用已驗證的 Starting Save checksum、世界種子、畫面／UI hash；偏航沿用 System.Random/net472 均勻 [-15,15]。seeds 固定 development 220100–220129，final 220200–220289，每份順序分配 mecha/camera/policy。工具由 Windows PowerShell 5.1 使用既有 C# Json encoder 生成 recorder 相同 manifest_id，registry 同步保留。實際執行前核對現場 baseline、設定、版本、注入校正與資源證據，僅有 manifest 不算試驗完成。

兩個合格凍結候選必須使用同一份 development manifest 清單、擾動及 policy seed，重試保持 manifest_id。先比較 matrix_done 完整成功數，再依 matrix_tech_done、manufacturing_done、logistics_done、metallurgy_done、electromagnetism_done、lander_done 到達數，第一個差異決定勝出；全同保留第二階段，時間不打破平手。Final 只執行選定模型 30 個有效回合，不參與選模。第三階段不合格不硬湊候選。

每回合從擾動完成第一個可控有效 RGB 起算 1800 秒 monotonic wall clock，排除載入，包含 UI／暫停；成功提前結束，死亡／不可恢復亦有效，停滯不提前終止。系統超標或人工介入為無效，以相同 manifest 重跑，連續三次無效停止批次。報總嘗試數、無效數／總嘗試、原因、重試、有效回合，不能丟棄無效紀錄。

控制 capture request→提交的 p95≤80 ms、p99≤100 ms、miss≤1%，不能連續五次 miss；分母為該回合可用控制步，miss 定義超過下一個 100 ms boundary。第一步 no-op，逾時釋放 held 並 no-op，不重複前一動作。另列 requested-to-observed 延遲。暖機後 DSP、錄製器、正式推理同開至少 30 分鐘，涵蓋主要 UI；整卡取樣峰值至少留 2 GiB 且無 OOM，報採樣間隔。上述實測不能由本協定生成取代。

16 個微任務及七個背景里程碑累計到達率 n/N，N 為全部有效回合；另報 active 啟用回合中的完成數／啟用回合數。非 active 完成可計累計到達，未啟用不算啟用後失敗。成功率及到達率報 Wilson 95% CI，z=1.959963984540054；N=0 時 rate/CI=null。到達者時間報 median／IQR，分位數固定線性插值，另列未到達數。Active 時間從提示啟用起算，背景從回合起點。零成功保留 0/N，不能用零秒代表無到達時間。

失敗可多標觀測／重建、注入、選錯動作、任務／reward 判定、停滯、原因不明，各需影片／事件引用。人工暫緩時待分類；不猜內因。停滯為超過 train 同 task 示範時長 p95 兩倍，至少 20 個不同回合的有效啟用→完成時長才校準，否則 null，不提前終止。

保存 checkpoint、配方、資料／評分版本、manifest、逐回合結果、原始計數、分母、影片、事件及失敗／無效紀錄。小樣本門檻與 development 勝出不支持顯著性或完整 Dreamer 4 復現主張。

世界模型互動診斷保留 12 個 validation 起始歷史，前三類各 4，從凍結預測名單依相同順序取；每個兩組事先描述動作，共 24 段，每段固定 task、最多 15 步後重設歷史。記方向、狀態、游標及失真首步，保留影片。人工執行暫緩，不新增 gate，不冒充真實遊戲成功率。
