# Issue #29 工程驗證

本紀錄對應 [#29](https://github.com/JayWu07291/DSP_Dreamer/issues/29) 的單回合模型閉迴路，並納入使用者核准的 DSP `0.10.35.29088` 相容性重驗。正式候選與同開資源驗收仍屬 #34／#35；本入口只接受 `engineering_only`、`qualified=false`。

## 逐項結案核對

2026-09-25 依 [#12 的工程結案分工](https://github.com/JayWu07291/DSP_Dreamer/issues/12)重查 #29 的五項要求，工程範圍均已完成。這項結論不改寫下列失敗試驗，也不表示正式延遲或模型品質通過。

| #29 要求 | 結案依據 |
| --- | --- |
| RGB、實際動作、17 維條件與共用排程 | 真實 checkpoint／子程序測試、跨提示保留歷史及回合重設；插件沿用正式進度判定與 task ID |
| 10 Hz、100 ms、首步 no-op、逾時釋放及遲到丟棄 | `PolicyRunner` 時槽與單一在途請求；120 ms 延遲實機試驗確認 5 次連續 miss、釋放、no-op 和 2 個遲到回覆丟棄 |
| 四段時間與每回合門檻檢查 | Python／C# 門檻邊界測試；實機結果分開保留 request 與 observed，超標明列 `system_latency`，未觀測成功明列 `injection_failure` |
| 基準擾動、30 分鐘、final observation、有效性與四檔 | 同一 manifest 重載與擾動；既有生命週期以 1800 秒截止，測試區分合法 death／timeout 與系統故障；實機最終觀測和封存完整 |
| 受控 checkpoint 實機閉迴路、逾時及停止 | 表列四份實機證據全部逐幀核對；F8 停止由使用者操作，停止後空按鍵狀態已觀測；所有產物維持工程身分 |

收尾重算六份完整模型試驗，結果與既有衍生結果一致，原始四檔數量、checksum 及資料集來源均相符；校正仍通過。此輪未修改執行程式，沿用下述 187 項完整測試結果。真正仍未通過的正式延遲、30 分鐘同開資源及合格候選試驗，分別由 [#34](https://github.com/JayWu07291/DSP_Dreamer/issues/34)／[#35](https://github.com/JayWu07291/DSP_Dreamer/issues/35)追蹤，不能因 #29 工程結案而啟動。

## 實作與可重跑檢查

| 要求 | 檢查 |
| --- | --- |
| 真實 checkpoint、RGB／實際動作／17 維條件 | `test_checkpoint_policy_rgb_history_and_episode_reset` 從 tokenizer、dynamics、agent 的正式訓練程式產生工程 checkpoint，再執行真實模型與子程序 |
| 提示切換保留歷史、回合重設、第一步 no-op | 同一測試核對跨提示歷史、重設後輸出一致與回合第一步 |
| deadline、miss 分母、連續五次 | `test_runner_deadline_denominators_and_consecutive_misses` 與 `ControlReplay` 核對 Python／C# 邊界 |
| 請求與觀測分開、失敗仍留四檔 | `test_runner_result_uses_observed_inputs_and_keeps_failure_separate` 經錄製、發布、編譯、讀回產生結果 |
| 逾時釋放後立即 no-op | `test_control_confirmation_and_release_from_compiled_evidence[release_noop]` 核對釋放窗口可跨 no-op，仍須讀到實際空 held |
| 釋放重試不得掩蓋前次失敗 | 同一測試的 `retry_release` 先重現錯誤通過，再核對第一組 release／no-op 失敗、第二次 release 成功；`final_noop_release` 保留無中間樣本的成組確認 |
| 新舊遊戲與未知 DLL | `test_live_lifecycle_without_baseline_cannot_publish` 核對兩個已知 hash 仍須通過其他來源驗證，未知 hash 拒絕 |

## 新版環境

新版 Assembly-CSharp SHA-256 為 `c43a484f6adf8a9e4b956156047070891b46860d5b5c707ba1377b6a2af25732`。以 Mono.Cecil 核對實際掛點與 `VFInput.OnUpdate` 的滑鼠軸／滾輪讀取順序，並在遊戲內確認 Harmony 載入及基準存檔可載入。原始 IL 摘要保留在 `runs/issue-29/runtime-hooks-0.10.35.29088.txt`。

第一版完整校正來源為 `51c00e32-47e5-41ef-8406-a2032d69e261.source`，21 個控制、雙軸各 11 級、三種滾輪、Numpad1 辨識與釋放均通過。四檔讀回核對 425 幀、21.293 秒、19.913 Hz、掉幀比例 0.468%。此校正只屬於插件 `ac57e327…`，不沿用到後續 DLL。

首次模型試驗 `cf737032-25c4-4206-9df8-edcc201f3407.source` 暴露 Unity Mono Stopwatch 與 Python QPC 原點不同，時間驗證拒絕首回應。失敗已封存，不能當作通過的控制試驗。修正後以非零 offset 的真實子程序測試核對時間上下界，並在每次啟動記錄換算 offset。

時鐘修正後，`c4612046-b265-4b91-9d1f-6d5db8260930.source` 暴露主執行緒低階 hook 與 SendInput 的等待問題。`33823bd7-efbc-4b22-af82-ae612f9b4b4a.source` 又暴露 worker 退出時過早清除身分、導致最後觀測未完成的清理問題。兩份失敗證據都保留，第二份維持 `INCOMPLETE.json`，不補造成功封存。

最終 DLL SHA-256 為 `10062c584f271eb7df2da8e25ed043f8df53b2ec5adea2ebaf4bbb2830f7a1f1`，runtime fingerprint 為 `55fc15914bfb466d7a1beceeb2031e9c703a4647219328bb5626e5e59ea1066d`。專用 hook 執行緒上線後，以原 checkpoint 重跑 `f0ca150c-69cc-4eb3-b65a-cbd2c3d5c21d.source`，首個複合動作 SendInput 為 21.156 ms，原先約 330 ms。這次 worker 仍因無法編碼的實際動作歷史退出，但 final capture 15、四檔、資料集與結果均完整。

新校正 `21b4c4f9-ca3e-4318-93c3-8aeee954768a.source` 全部控制通過，421 幀逐幀 RGB 比對、21.116 秒、19.890 Hz、掉幀比例 0.473%。校正檔 `runs/issue-29/calibration-hooks.json` SHA-256 為 `cb59e0f0fbd932d2b8ba27e1ea668b2d47bb0551a209f777ec88747a1f2a48b7`。

## 閉迴路與故障證據

| 試驗 | 證據根目錄，位於 `runs/issue-29/live/` | 結果 |
| --- | --- | --- |
| 200 步工程 checkpoint | `f6082f3a-35ec-4d05-a4df-5441692910de.source` | 模型非空按鍵與所有 fallback 均由 DSP 觀測確認；UI 切換使實際歷史無法編碼，五次 miss，判無效並保留 final capture 14 |
| 額外 120 ms 推理延遲 | `4fed8789-f4d4-490e-8514-0935a1072500.source` | 6 個控制步，5 次連續 miss；2 個遲到回覆丟棄；所有 no-op 與必要釋放均有實際樣本；只有 `system_latency`，final capture 12 |
| 1000 步工程 checkpoint | `eb217ab8-aaac-4a65-a591-8170d4b8de36.source` | 47 個控制步全部有實際觀測，必要釋放均確認；6 次 miss、最長連續 5 次，p95 150.495 ms、p99 153.107 ms；判無效並保留 final capture 91 |
| 使用者按 F8 停止 | `dc01ab11-db37-471a-8cfc-58afeb145e0b.source` | 31 個控制步後收到 `stopped`；停止 release 8133 送出 25／25 個輸入，41.844 ms 後樣本 8134 為空 held 並含 F8 up；final capture 64、四檔、資料集及結果完整 |

表中四份試驗均已完成四檔讀回及逐幀 RGB 比對。停止試驗為 65 幀、3.211 秒、19.928 Hz、零掉幀；F8 人工輸入使最後一個 action 的 held 狀態改變，結果保留 `stopped`、`unknown_control`、`injection_failure` 及 `system_latency`，不宣稱有效代理成果。1000 步 checkpoint SHA-256 為 `cb350892f0636bca2c5d99b3372df5a8146b6c5c41432f08baf773e74f1da4da`，由既有 AgentTrainer 在合成 no-op 資料上訓練產生，沒有改寫模型輸出或跳過真實推理。

兩次長度增加試跑在約 47／49 個控制步後出現連續逾時。獨立 GPU 量測顯示，64 步歷史的 CUDA 閒置配置累積至 10,852 MiB，推理超過 300 ms；逐步清除閒置配置後，64 步以後約 43–52 ms，該次量測返回後的保留配置為 24 MiB。修正只釋放不用的配置，不縮短歷史。這是定位與改善記憶體累積的工程量測，不是端到端延遲 gate 通過證明。

修正釋放觀測窗口後，已重新讀取校正與五份已完成模型試驗。校正仍通過，重算結果另存 `.source.rechecked.json`，原始四檔及先前結果保留。兩軸審查未留下阻擋工程閉迴路驗收的問題；無中間 DSP 樣本的連續釋放只能確認整組操作後的空狀態。

deadline 檢查在 Unity `Update()` 執行。若主執行緒停頓，控制釋放也須等它恢復；這類試驗會因延遲超標判無效，不能解讀為停頓期間仍保證 100 ms 內釋放。

## 最終檢查

完整測試套件 **187 項通過**，耗時 443.94 秒，沒有失敗或略過。報告為 `runs/issue-29/final-suite.xml`；20 個 warnings 來自既有 torchvision 參數淘汰提示。控制與 runner 的針對性測試先行通過 20 項；mypy 檢查 31 個來源檔案通過，Recorder Release 建置零警告、零錯誤。

早期 ControlGuards 可執行檔曾被 Windows 應用程式控制政策封鎖。最終完整測試已直接執行重新建置的程式，核對本機與已部署 DLL，兩者均通過 human／policy guards、worker 故障及 hook 執行緒檢查。最終 EXE SHA-256 為 `425ee8f777f13f16bed9754c2d58e07ce0aec45a3ab302e57895da65999fc5e5`。未變更安全設定，也未改用其他載入方式。

## 重跑方式

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --configuration Release
```

操作與證據格式見 [runner.md](runner.md)。本機原始檔保留在 `runs/issue-29/`，不納入 Git；工程結果不授予正式品質資格。
