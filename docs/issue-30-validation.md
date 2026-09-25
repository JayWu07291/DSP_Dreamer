# Issue #30 工程驗證

本票依 2026-09-25 的結案範圍修訂，交付固定 manifests 的批次工具、選模及統計匯出。實作與使用方式見 [批次試驗說明](evaluation-batch.md)。工程 fixtures 沿錄製四檔、正式 compiler、dataset loader、#29 `episode_result` 執行，不替換評分器，也不提交預先編好的成功數。

## 驗收對照

| 規則 | 工程驗證 |
|---|---|
| 同 manifest 重試、保存無效原因 | 31 次嘗試中 1 次人工介入無效，重試使用相同完整 manifest，累計 30 個有效 final 回合 |
| 連續三次無效停止 | 原 manifest 留下三份獨立 request／response／result；只重跑兩次，不推進下一份 manifest |
| 雙候選相同 10 development manifests | 第二、三階段各 10 個有效回合後才選模；七個比較層級逐一驗證較高層優先 |
| 平手保留第二階段 | 兩候選到達數相同，即使第三階段較快仍選第二階段；選模先於 final 封存 |
| 單／無候選 | 單候選直接執行 final；空清單或資格 fixture 未通過時不呼叫單回合執行器 |
| 全成功／零成功 | 全成功保留 30/30，Wilson 95% CI 為 [0.8864866068260312, 1]；零成功保留 0/30，CI 為 [0, 0.11351339317396876] |
| 累計／active 分母 | 非 active 完成計入累計到達數，啟用分母保持 0；未啟用不計為 active 失敗 |
| 到達時間 | Active 由提示啟用、背景由回合起點起算；線性插值 median／Q1／Q3／IQR，無到達或無啟用起點保留 null |
| 停滯與失敗 | 19 個有效 train 回合不校準，20 個才使用 2×p95；validation 不補配額，多標分類核對影片／事件引用，停滯不提早終止 |
| 隔離及拒收 | 正式模式與正式保留 manifests 被拒收；checkpoint 修改、錯誤重試 manifest、執行器故障均不能成為有效回合 |

每個已完成的批次保留 `plan.json`、`calibration.json`、`selection.json` 如適用、`report.json`、`nodes.csv` 及逐次證據。報告固定 `engineering_only=true`、`qualified=false`、`formal_valid_episodes=0`。試驗結果與 checksum 索引見 [機器核對紀錄](issue-30-validation.json)。本機原始測試產物位於 `runs/issue-30/`，未納入 Git。

## 檢查與審查

14 個批次整合案例通過，涵蓋本票既定 fixtures 與 CLI 執行器故障。完整 pytest 套件共 201 項通過，耗時 693.48 秒，沒有失敗或略過；20 則 warnings 為既有 torchvision 參數棄用提示。`mypy dsp_dreamer` 檢查 32 個來源檔案通過，`git diff --check` 通過。16 份批次報告的封印、錄製 manifest 與 dataset COMPLETED checksum 已重新核對，結果收在機器核對紀錄。

依 implement 技能分別執行 Standards 與 Spec 審查。Standards 未發現規範或程式碼異味問題，兩處繁簡字形已修正；Spec 未發現可證實的需求缺失或範圍外行為。

## 正式驗收界線

本次沒有執行正式 development 或 final 回合，也沒有用工程結果挑選正式模型。#29 仍只接收工程 checkpoint；正式 admission、適用的離線 gate、實機資源與延遲 gate 以及正式 runner 身分，須由 #32／#33／#34／#35 完成串接與驗收。既有正式 manifests 的輸入設定差異仍未因此解除。

這些測試證明批次工具的重試、選模及統計行為，不證明模型在遊戲中的成功率、30 分鐘資源表現或正式候選資格。
