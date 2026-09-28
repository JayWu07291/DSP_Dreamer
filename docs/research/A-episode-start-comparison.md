# A 回合開頭片段抽樣對照

2026-09-27。依[問題畫面抽樣檢查](A-screen-sampling-audit.md)，只比較是否補充連續回合開頭片段。使用者認為每組 1000 步耗時過長，改為每組 100 步的短對照，由使用者在外部 PowerShell 啟動。

兩組已完成，見[100 步對照結果](A-episode-start-results.md)。開局平均改善，但多出的 UI 仍在，整體平均沒有提升。

## 兩組共同條件

| 項目 | 設定 |
| --- | --- |
| 初始化 | `runs/A-20260927-104240-538709/training/final-1000.pt`，已累計 3431 次更新 |
| 新增更新 | 每組 100 次完整 optimizer update，各自到累計 3531 次 |
| 時間上限 | `None`，中斷遺失的更新重跑直到達標 |
| seed | 20260928，兩組相同 |
| LR | peak `2e-5`，10 步 warmup，cosine 降至 `1e-5` |
| 有效 batch | microbatch 2 × accumulation 8，共 16 段 |
| 片段長度 | 16／48 幀，三短一長 |
| 遮罩 | 每張圖 `p ~ U(0, 0.9)` |
| loss | RMS 正規化 MSE + 0.2 × RMS 正規化 LPIPS |
| 初始化狀態 | 保留共同來源的模型權重與 loss RMS；兩組分別重設 optimizer、排程、RNG、history |
| 驗證與存檔 | 每 50 步或 1800 秒，先到者；完成後固定 200 張完整評估 |
| 資料讀取 | `verify_rgb=False`，沿用不可變資料；仍核對 metadata、索引、split 與凍結評估檔 |

模型、其他優化參數、資料和 gate 均沿用上一輪。兩組共同 seed 改為新值，避免照上一輪的順序重播；`warmup_fraction=.1` 保留 10 步 warmup，cosine 排程在本輪 100 步內完成。補充組只比基準組多一項設定差異。

| 組別 | 設定檔 | `STAGES['A']['episode_start_sequences']` |
| --- | --- | ---: |
| 基準組 | [training_config_A_uniform.py](../../training_config_A_uniform.py) | 0 |
| 補充組 | [training_config_A_episode_start.py](../../training_config_A_episode_start.py) | 1 |

兩組都從同一份 3431 次權重開始，不能用基準組的新權重初始化補充組。兩組也不能並行使用同一份訓練帳本。

## 唯一變項的定義

先照原演算法抽滿 16 段，再用同一個只依賴 seed 與 step 的抽樣 RNG，均勻選一個 slot，替換成 train 中的合法回合起點。其他 15 個 slot 的來源、起點和遮罩 RNG 保持一致。每組都處理 1600 個片段、38,400 次 target 影格曝光。

`episode_start_sequences=1` 表示每批固定補充一段，占片段數的 6.25%，不表示開局畫面恰占所有 target 影格的 6.25%。原均勻樣本也可能抽中回合起點；因此實際回合起點段數可能略高於 100。替換是為了固定總訓練量，沒有追加第 17 段。

回合起點須是 dataset 的 `is_first`，而且同時位於該長度的 `ModelView.sequence_starts()` 合法清單。僅從 train 中符合這兩項條件的起點均勻抽樣。第一段無效、太短或跨缺口的回合不進入該長度的補充池，不把後面的第一段有效資料冒充回合開頭。短長補充池各自建立，任何必需的池為空就拒絕執行。task ID、UI 特徵和 validation 圖均不參與訓練抽樣。

預設配方維持 0。設定、checkpoint、`recipe.json` 和每步 log 均記錄補充數量，原有 `samples` 保留全部 16 個實際來源位置。使用同一配置恢復時，下一步抽樣可重現；OOM 後換成 1／16，總補充數仍是一段。

## 實際抽樣清單已核對

用新設定重播各 100 步抽樣，未執行模型更新。每一步恰好替換一個 slot，其餘 15 個 slot 完全一致。合法短／長均勻池分別有 132,334／122,010 個起點，合法回合開頭池則有 44／22 個起點。補充組實際取到 100 個回合開頭片段，基準組為 0 個。

下表沿用前次稽核的影像特徵快取，並與本次通過凍結核對的來源、合法影格、observation index、task ID 逐項匹配。沒有重新讀取全量 RGB。

| 畫面類型 | 基準組曝光 | 補充組曝光 | 基準組有此畫面的更新 | 補充組有此畫面的更新 |
| --- | ---: | ---: | ---: | ---: |
| 開局，下角 HUD 尚未完整出現 | 35，0.091% | 1,283，3.341% | 5/100 | 100/100 |
| 開局，下角 HUD 已出現、研究 UI 不可見 | 56，0.146% | 257，0.669% | 5/100 | 64/100 |
| 科技樹 | 948，2.469% | 806，2.099% | 40/100 | 36/100 |
| 一般遊戲中研究列不可見 | 4,843，12.612% | 5,413，14.096% | 87/100 | 100/100 |

影格類別可能重疊；比例分母都是 38,400。這些是確定 seed 下的抽樣清單統計，分類本身仍是前次視覺抽查支持的估計，不是新的模型品質結果。科技樹曝光略減是替換抽樣的結果，完成後須檢查是否影響重構。

共同來源 checkpoint 已通過 checksum、凍結身分、模型配置和四個模型運算檔案指紋核對，並以真實 `TokenizerTrainer.initialize_from()` 在 CPU 載入權重及 RMS。step 保持 0，optimizer 無狀態；正式帳本和來源 checkpoint 指紋前後一致。證據見[100 步抽樣與初始化核對](../../runs/issue-31/A-episode-start-checks/sampling-100.json)。

## 執行

關閉 DSP，在外部 PowerShell 進入 repo。先完成基準組：

```powershell
cd E:\GitHub\DSP_Dreamer
.venv/Scripts/python.exe -X utf8 tools/train.py A run --restart --config training_config_A_uniform.py --init-from runs/A-20260927-104240-538709/training/final-1000.pt --output runs/A-uniform-3431-100
```

確認 `runs/A-uniform-3431-100/training/run.json` 的 `status` 是 `completed`、`updates` 是 100，且完整 `training/gate/metrics.json` 含 200 張，再執行補充組：

```powershell
.venv/Scripts/python.exe -X utf8 tools/train.py A run --restart --config training_config_A_episode_start.py --init-from runs/A-20260927-104240-538709/training/final-1000.pt --output runs/A-episode-start-3431-100
```

第二組的 `--restart` 會在自己的 `.logs/previous-budget.json` 封存基準組帳本，再開始新實驗。兩組的 checkpoint、圖和 log 都保留。若第一組未完成，先恢復第一組，不要執行第二個命令。兩組之間不要修改 Python 實作或任何共用設定檔。

每組會先執行四步測速，再重新載入共同來源開始正式 100 步；測速更新不帶入正式權重。以先前約 30 秒／步估計，每組更新約 50 分鐘，另加 metadata 載入、測速、驗證與存檔，兩組合計約 2 小時，建議預留約 12 GiB 輸出空間。這是估計，不是時間截止。

可先用 `A show-config --config <設定檔>` 查看完整解析設定，不讀資料或改帳本。中斷時改用下列格式，配置選當前組，checkpoint 選帳本最新的完整存檔，輸出目錄另取未使用的名稱：

```powershell
.venv/Scripts/python.exe -X utf8 tools/train.py A train --config <當前組設定檔> --checkpoint <本組最新checkpoint> --output <新的恢復輸出目錄>
```

恢復不要加 `--restart` 或 `--init-from`。如發生 CUDA OOM，依[原有 OOM 恢復流程](../training.md)重測 1／16。若只有其中一組改用 1／16，另一組也應採相同 microbatch 再比較，因為 microbatch 分組會影響遮罩 RNG 和 RMS 統計，僅抽樣相同不足以排除這項差異。

## 完成後如何判讀

主要比較完整 gate 中 R001–R010 這十張固定 `task_id=0` 圖的逐張與平均原始 MSE／LPIPS，並並排看 R001、R004 等圖原本不存在的 UI 是否減少。定期驗證只有前八張，另列趨勢，不混入十張或完整 200 張的平均值。

同時比較完整 200 張及另外 190 張，檢查整體細節是否退步。R016 科技樹和 R100 遊戲中畫面作為既定參考，這次沒有科技樹的專用補充池。兩組訓練分布不同，running RMS 也會隨之變化，因此不靠訓練總 loss 或混合後的 training MSE／LPIPS 判定勝負。

這 100 步用來找早期改善訊號。若補充組開局指標改善、原本多出的 UI 也減少，而且其他畫面沒有明顯退步，才支持後續沿用這項抽樣。若只有數值改善而 UI 錯誤仍在，就記為部分改善；若沒有差異，記為本次短對照未觀察到效果，不能宣稱抽樣假說已被排除。單一 seed、100 步不足以判定收斂或統計顯著性，也不取代原有人工品質 gate。後續不自動追加 900 步。

完成兩組後回報輸出目錄；若曾恢復，連同各次恢復目錄一起提供，以串接完整 log。此次工程驗證不授予 A 品質資格，不啟動 B。

## 工程驗證

`tests/test_tokenizer.py`、`tests/test_training_settings.py`、`tests/test_training_control.py` 共 18 項通過，耗時 404.58 秒，12 則警告來自既有 torchvision 介面棄用。涵蓋 train 限制、非法回合起點排除、其他 slot 不變、未開啟時重現原抽樣、checkpoint 恢復和完成更新數的控制。縮短為 100 步後，設定對照測試再通過，兩份 CLI `show-config` 輸出確認只差補充段數；第一、十、第一百步 LR 分別是 `2e-6`、`2e-5`、`1e-5`。三個實作／設定檔的 mypy 通過。

JUnit、解析設定及 CPU 抽樣檢查保存在本機 `runs/issue-31/A-episode-start-checks/`。測試只使用合成資料及隔離帳本；真實資料檢查未做 GPU 推論、optimizer 更新或全量 RGB 核對。
