# Dreamer 4 多任務訓練與 VPT 鍵鼠動作表示

## 結論先行

Dreamer 4 的 Minecraft 實驗其實很接近本專題目前選定的做法。它用一個共享模型學 20 個帶 `task_id` 的小任務，訓練時從完整遊玩資料抽取與各任務相關的片段，評估時則從空背包、隨機世界開始一個 60 分鐘 episode，依照固定 prompt sequence 逐步切換 task，並統計沿途取得的 milestone。論文沒有為 20 個任務各建一個獨立起始存檔，也沒有報告 20 組獨立 episodic success rate。

「低階原始鍵鼠動作」也不等於讓神經網路直接回歸 Windows 原始事件。Dreamer 4 把鍵盤表示成多個二元分布，把滑鼠兩軸先量化，再合併成 121 類的 categorical distribution。VPT 更進一步把互斥按鍵組合與「是否移動滑鼠」做成 8,461 類的 joint hierarchical head，只有 camera-on 時才使用另一個 121 類 camera head。因此，先前 Q16 的 A 並不是 Dreamer 4 或最終 VPT policy 的原樣做法。

## 1. Dreamer 4 如何做 multi-task

### 1.1 模型中的 task conditioning 與 heads

以下是論文明說：

- 世界模型預訓練完成後，作者在 dynamics transformer 中插入 agent tokens，並把 task embedding 輸入 agent tokens。agent tokens 可以注意自己和其他 modalities，但 image、action、register 等其他 tokens 不能反向注意 agent tokens。這個單向遮罩使世界的未來只能由 action 直接影響，不能讓 task 偷渡進世界動態。來源：Dreamer 4，第 3.3 節，PDF 第 6 頁。
- policy head 與 reward head 都從每個 timestep 的 agent token output embedding `h_t` 預測。第二階段同時給資料 `z, a, q, r`，其中 `q` 是 task，並用長度 `L=8` 的 multi-token prediction 同時預測當下到未來 8 個距離的 action 與 reward。各距離各有一個小 MLP output layer。來源：第 3.3 節、式 9，PDF 第 7 頁。
- reward head 使用 Dreamer 3 的 `symexp twohot` distribution。policy head 依資料集動作空間使用 categorical 或 vectorized binary distribution。來源：第 3.3 節，PDF 第 7 頁。
- value head 到 imagination training 才初始化。它從 imagined state 預測未來折扣 reward 的 `lambda-return`，同樣使用 `symexp twohot` output。來源：第 3.3 節、式 10，PDF 第 7 頁。
- Minecraft 實作用 one-hot task indicator，並明說也可以改用 text embedding。作者為 20 個任務標註 sparse binary rewards。任務包含採礦、合成、開啟工作台或熔爐、放置，以及使用不同 pickaxe。來源：第 4.1 節，PDF 第 10 頁；附錄 C 表 4，PDF 第 27 頁。

可以合理推論但不能寫成論文明說：task embedding 很接近我們的離散 `task_id -> learned embedding`。論文沒有公開 task embedding 的維度、agent token 數量、reward event 的時間展開方式，也沒有說 sparse reward 是否在達標後持續為 1。

### 1.2 資料抽樣與 agent finetuning

論文明說的 mixture 是：

- 50% uniform sequences，從固定 VPT contractor dataset 均勻抽樣。
- 50% relevant sequences，這些片段完成 20 個任務中的至少一項。
- behavioral cloning loss 只算 relevant fraction。
- dynamics loss只算 uniform fraction，作者說這是為了避免 optimistic generations。
- 這個 mixture 用來放大 behavior cloning、reward modeling 與 reinforcement learning 的 task signal。來源：第 4.1 節，PDF 第 10 頁。
- Agent finetuning 並未停止世界模型目標。作者保留預訓練時的 noisy representation 與 video prediction loss，再加上 policy/reward MTP loss，以避免破壞已有能力。來源：第 3.3 節，PDF 第 7 頁。

論文沒有說明：

- relevant sequence 的時間窗在事件前後各取幾秒。
- 20 個 task 之間是否等機率抽樣，或按資料量抽樣。
- 同一段序列同時符合多個 task 時如何複製或指定 `q_t`。
- train/eval 的 event annotation 程式與 reward labeling 程式。Dreamer 4 沒有在本 repo 提供原始碼。

對 DSP 的直接含意：只錄從開局開始的完整流程沒有問題，但訓練 loader 應依 C# event marker 建立 relevant windows，並與 uniform windows 做 50/50 mixture。這是沿用論文的資料策略。若完全不切片、不平衡抽樣，就不是 Dreamer 4 的 Minecraft agent finetuning 做法。

### 1.3 imagination training

論文明說：

- imagined rollout 從前兩階段使用的 dataset contexts 開始。每個 context 只啟動一條 rollout，以增加 context 多樣性並降低記憶體用量。
- transformer 反覆展開自己。flow head 取樣 latent representation，policy head 取樣 action，reward head 與 value head 再為軌跡標註 reward 與 value。
- 默認只更新 policy 與 value heads，凍結 transformer。完整 transformer finetuning 只有小幅好處且較昂貴，若要做還必須保留 dynamics、policy prior 與 reward losses。
- value 使用 `gamma=0.997` 的 TD lambda-return。policy 使用 PMPO，只取 advantage 的正負號，不用大小。作者把 batch 與 time 上所有 imagined states 分成正、負集合，各自平均 loss，使不同 reward scale 的 tasks 得到相同比重。
- policy loss 加 reverse KL 到 agent finetuning 結束時凍結的 behavior policy prior，係數 `beta=0.3`；正負集合權重 `alpha=0.5`。來源：第 3.3 節、式 10 至 11，PDF 第 7 至 8 頁。

論文沒有清楚交代 imagination context 的 task-balanced sampler，也沒有說每條 rollout 中途是否切換 task。依 agent token 每步收到 `q_t`、evaluation 使用 prompt sequence 來看，系統有能力逐步改 task；但「imagination 中也按完整 prompt sequence 跑」只能算推論。

### 1.4 評估到底是完整流程還是獨立微任務

答案是完整長 episode 加上階段式 task prompts。

Dreamer 4 在 Offline Diamond Challenge 中，每個 episode 都以空背包進入隨機生成世界，持續 60 分鐘。作者用附錄表 6 的 linear prompt sequence 引導同一個 policy。sequence 依序要求採木頭、做木板、工作台、木鎬、石鎬、熔爐、鐵鎬，最後採鑽石。作者用 1,000 個 episode 統計沿途 milestone item 的 success rate，也統計成功 episode 抵達各 milestone 的時間。來源：第 4.1 節，PDF 第 9 至 12 頁；附錄 C 表 5 至 6，PDF 第 27 頁；附錄 D 表 7 至 8，PDF 第 28 頁。

這裡要分清兩種評估：

- **Agent 評估。** 從單一開局連續跑完整流程。20 個 task 是 prompt vocabulary，不是 20 個獨立 benchmark 存檔。
- **World-model human interaction 評估。** 人類拿到一項任務與相應 start frame，直接在生成模型內操作；這是檢驗 object interaction 與 game mechanics，不是 agent multi-task 成功率。來源：第 4.2 節，PDF 第 12 頁及附錄 G 至 I。

因此，DSP 可以從開局跑完整 episode，隨進度把 `task_id` 從「拆登陸艙」切到「研究電磁學」、「接近鐵礦」、「放置採礦機」，並同時計算每個 checkpoint 的到達率與完整成功率。這比為每個微任務另做存檔更接近 Dreamer 4。不過 Dreamer 4 的起始世界本身是隨機生成；DSP 若以程式改玩家位置、鏡頭或礦脈，就屬於我們自己的 benchmark 設計，不能歸給論文。

## 2. Dreamer 4 與 VPT 的鍵鼠 action

### 2.1 Dreamer 4 的通用 action encoder

Dreamer 4 的 dynamics model 允許 action 有多個 component。每個 component 先各自編成 action tokens，再與 learned embedding 相加。continuous component 用 linear projection；categorical 或 binary component 用 embedding lookup。來源：第 3.2 節，PDF 第 5 頁。

這是 dynamics 的 action input encoding，不等於 policy output distribution。對 Minecraft，論文另行指定 policy output：23 個 keyboard binary distributions，加上一個 121 類 mouse categorical。來源：第 4.1 節，PDF 第 10 頁。

附錄 A 說得更具體。鍵盤先轉成 binary vector；mouse 的每一軸用 mu-law 編碼並量化成 11 bins，接著列舉 `11 x 11 = 121` 個二維組合，成為一個 categorical variable。影片是 360 x 640、20 FPS。來源：附錄 A，PDF 第 25 頁。

所以 Dreamer 4 Minecraft 不是：

- 直接回歸連續 `mouse_dx, mouse_dy`。
- 每個滑鼠軸各自獨立 categorical。
- VPT 的 8,461 類 hierarchical joint buttons head。

論文稱其輸入輸出為 low-level mouse and keyboard actions，意思是沒有 `craft_item` 之類巨集動作，不代表保留作業系統事件的連續精度。來源：附錄 E 至 F，PDF 第 29 頁。

### 2.2 VPT 的 factored 與 hierarchical mapping

VPT Appendix C 的人類介面包含 20 個 binary controls：前後左右、jump、inventory、sneak、sprint、attack、use、drop、hotbar 1 至 9。任意文字輸入被排除。mouse 是相對位移，在一般畫面改 yaw/pitch，在 GUI 中移動 cursor。兩軸各用 11 個 foveated bins，小位移較細、大位移較粗。來源：VPT 附錄 C.2、表 3 與圖 13，PDF 第 21 至 23 頁。

VPT 有兩種容易混淆的 representation：

1. IDM 使用 factored heads。每個 key 各有一個 2 類 on/off softmax，mouse X 與 Y 各有獨立 11-way categorical。所有 head 的 negative log-likelihood 相加。來源：附錄 D.1 至 D.2，PDF 第 23 至 24 頁。
2. 最終 BC policy 使用 joint hierarchical action space。它先把互斥組 `forward/back`、`left/right`、`sprint/sneak`、`hotbar 1..9` 與其餘 binary actions 組合，再加入 camera on/off。第一個 categorical head 有 8,461 類；只有 camera-on 時才啟用第二個 121 類 joint X/Y camera head，否則遮掉 camera loss 並不取樣 camera。inventory 與其他按鍵和 camera 互斥。來源：附錄 E.3，PDF 第 25 至 26 頁。

作者選 hierarchical mapping 的理由不是壓縮資料檔，而是 factored Bernoulli 或 categorical heads 無法描述按鍵間相依性。論文的例子是人類可能只做 `forward+attack` 或 `left+drop`，完全獨立的 heads 卻會錯誤組出其他組合。實驗中 factored policy 也取樣出更多 null actions。來源：附錄 E.3，PDF 第 25 至 26 頁。

本 repo 的參考碼吻合論文：

- `reference_codes/Video-Pre-Training/lib/actions.py:18-39` 列出 20 個 buttons；`:48-103` 實作 linear 與 mu-law camera quantizer；`:132-176` 在環境格式與 `buttons` binary vector、`camera` 兩軸 bins 間轉換。
- `reference_codes/Video-Pre-Training/lib/action_mapping.py:18-29` 定義互斥 button groups；`:120-230` 實作 `CameraHierarchicalMapping`，輸出 joint `buttons` categorical 與 121 類 `camera` categorical。
- `reference_codes/Video-Pre-Training/lib/action_head.py:93-161` 實作 categorical log-softmax、NLL、sampling 與 KL；`:164-197` 讓 dictionary 中各 action head 的 log-probability 相加。
- `reference_codes/Video-Pre-Training/inverse_dynamics_model.py:15-33` 使用 mu-law、11 bins 與 factored `IDMActionMapping`；`reference_codes/Video-Pre-Training/agent.py:41-44,115` 則使用相同 camera quantizer 加 hierarchical policy mapping。

這份 release README 與 `data_loader.py` 明說它不是論文實驗的原始 loader。它可用來理解格式與映射，不能拿來證明論文訓練時所有資料清理細節。

### 2.3 20 Hz 對齊

VPT 說 native human interface 以 20 Hz 運作。其修改版 Minecraft 把 server 與 client 放在同一 thread、同一 frequency，policy evaluation 的每一步因而有一張 observation 和一個 action。60 分鐘等於 72,000 個 actions。來源：摘要、主要實驗與附錄 C，PDF 第 1、5、21 頁。

Dreamer 4 使用 VPT contractor gameplay，明列 video 與 mouse/keyboard actions 為 20 FPS，且說資料更新率與遊戲相符。來源：第 4 節，PDF 第 9、12 頁；附錄 A，PDF 第 25 頁。

可以直接沿用到 DSP 的原則是建立固定 tick dataset：每個 tick 保存 observation frame、該時間區間實際生效的 held-key state、button transitions 或 click state、累積相對 mouse delta、task id、reward/event 與 episode metadata，而且推理時使用相同 tick rate。

但論文沒有替 DSP 決定下列細節：

- 必須使用 20 Hz。這是 Minecraft 的 game update rate，不是 Dreamer 4 架構限制。12 GB GPU 下可以先比較 5、10 Hz，UI click duration 仍須至少占一個 tick。
- Windows hook event 和 frame 的先後順序。應由 DSP recorder 訂明 `frame_t, action_t -> frame_{t+1}` 的契約並做延遲校正實驗。
- 多個 OS mouse events 如何聚合。合理做法是每 tick 加總 `dx/dy`，但這是 DSP 設計。
- scroll wheel、任意鍵盤字元、key-down/key-up event 是否進模型。VPT 排除了任意文字，也沒有把 scroll wheel 當獨立 policy head。若 DSP 保留完整 Windows key domain 與 scroll，它是擴充，不是沿用 VPT。

## 3. 對 DSP action 設計的建議

如果目標是「效仿 Dreamer 4」，第一版應選 Dreamer 4 Minecraft mapping，而非連續回歸：

- recorder 原始層保留完整可重播事件，包括 timestamp、key down/up、mouse buttons、relative `dx/dy`、wheel。
- dataset model view 以固定 tick 聚合 held-key binary vector。mouse 兩軸先 mu-law 或 foveated quantization，再合併成 joint categorical。wheel 可另設小型 categorical，包含負、零、正，因為論文沒有處理它。
- dynamics action encoder 為每個 component 各自 embedding 後相加，這直接沿用 Dreamer 4 第 3.2 節。
- policy head 先做 vectorized binary keyboard 加 joint categorical mouse，這是 Dreamer 4 Minecraft 的明確做法。若 null action 或不合理按鍵組合成為主要問題，再加入 VPT hierarchical joint mapping 作消融實驗。

不能聲稱「保留完整原始鍵鼠輸出且完全沿用 Dreamer 4/VPT」。只要模型使用 bins、互斥組或排除任意字元，就已經是保留低階控制語意、但經過模型化的 action space。更準確的報告措辭是：「代理使用低階鍵鼠控制，不使用遊戲巨集動作；錄製器保留原始事件，模型端採用 Dreamer 4/VPT 式離散化。」

## 來源

- `papers/Training Agents Inside of Scalable World Models.pdf`，第 3.2、3.3、4、4.1、4.2 節與附錄 A、C、D、E、F。
- `papers/[15]Video PreTraining (VPT) Learning to Act by Watching Unlabeled Online Videos.pdf`，第 3、4 節與附錄 C、D、E。
- `reference_codes/Video-Pre-Training/lib/actions.py`
- `reference_codes/Video-Pre-Training/lib/action_mapping.py`
- `reference_codes/Video-Pre-Training/lib/action_head.py`
- `reference_codes/Video-Pre-Training/inverse_dynamics_model.py`
- `reference_codes/Video-Pre-Training/agent.py`
- `reference_codes/Video-Pre-Training/data_loader.py`
