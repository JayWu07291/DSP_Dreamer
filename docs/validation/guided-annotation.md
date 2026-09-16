# 引導式標註準備

更新：Jay 已完成下列 5 題，原答案與草稿保存於 `runs/annotation-submissions`。目前沒有待補回答；控制版本更新後的來源核對與下一步見 [catalog v4 驗證報告](catalog-v4.md)。下文保留當時交付準備紀錄。

2026-09-16，使用者完成兩題練習並確認理解後，要求繼續做到需要人工處理為止。本輪準備 5 個局部判讀題、回答保存與匯入檢查。沒有新增訓練依賴、改寫 evaluation-v1，或將練習／瀏覽器測試當成人工真值。

## 已完成

- 第一批使用既有 validation 原圖 R031、R041、R051、R071，共 5 個物品／數字位置。框選由助理查看原圖後準備；每題都要求人工確認位置正確，沒有附示範答案，也沒有預填物品或數字。
- 只放大無損 PNG。每題綁定原 workbench、輸入包、來源、capture、box 與 image SHA-256；匯出拒絕素材異動、來源／輸出重疊及覆寫。
- 回答包含判讀者與含時區時間。物品和完整數字分開保存，數字以字串保留前導零。「看不清楚」保存原圖不可辨識的排除原因；「框錯位置」保留待修題，不當成可排除項目。
- 每題確認後保存到瀏覽器，支援備份匯出、可見 JSON、複製與貼上匯入。未確認的修改會阻止換題／匯出，離開時提醒；儲存失敗會提示備份。
- `check` 指令核對整個交付包及答案來源，再轉成既有 `dsp-annotation-draft/1`。每個局部 item 保存其判讀者；整張圖 `reviewed=false`，UI 區域尚未確認，整圖確認數維持 0。

交付目錄為 `runs/guided-annotation-v2`，網址是 [5 題標註頁](http://127.0.0.1:8828/)。批次 ID 為 `d35b0d19c330d0fbc893e1a3587429169bdde7fd722f2efda6a955408e6939a0`，匯出包 ID 為 `27428b9de46222c24f50e1069b353425c198d1e07b7fc01ec3e69eda0d946ee0`。`batch.json` 保存題目與來源，`export.json` 保存 7 個檔案的 checksum。v1 保留為檢查過程，v2 修正物品選單的遊戲名稱「磁線圈」。瀏覽器測試使用 `QA_ONLY`，交付前清空測試回答，保持 0/5；人工回答目前仍待收到。

## 現在需要人工做的事

1. 在新頁填名字或固定暱稱。每題看黃色框與放大圖，選可否判讀，能辨認時選物品、填完整數字，按「確認並儲存這題」。看不清楚或框錯時照實選，不必猜，也不用自己改框。
2. 做完按「匯出目前回答」，再按「複製回答」貼回對話。可以中途備份，不要求一次完成。我會核對回答、處理錯框與排除，再安排其他類型的題目。
3. 補錄的第一步仍需開啟 DSP，進入可操作畫面後按一次 F6，再回報「F6 已按」。新版 DLL 已部署，但目前 runtime-candidate 仍是舊 DLL 的指紋，不能據此核准新版本。這一步只是產生新指紋；核對後才安排第二次 F6 的校正探針，通過後再按 F8 補錄。

## 剩餘依賴

目前資料仍為 train 8、validation 1、offline-test 0 個有效完整回合；每微任務 20/3/3 正例 gate 未通過。200 張重建候選的逐任務配額仍缺 32 張，預測四類各 50 段仍待人工確認。第一批只有物品／數字，游標、選中配方、連接端點／方向／狀態，以及五類 UI 的完整標註仍未完成。

補錄會改變索引與抽樣名單，因此本批保留為來源可追溯的局部草稿；後續只能在核對同一原圖後沿用，不能直接凍結到新輸入包。其餘題目隨人工回報與補錄後的來源準備，避免在來源未定時一次標完舊名單。40 個 development／final manifests 的輸入設定 hash 仍與目前遊戲設定不同，正式試驗前須另行對齊或建立新協定版本。這些缺口均未以本批工具檢查宣告通過。

## 重現與檢查

```powershell
.venv\Scripts\python.exe tools/guided-annotation.py export --workbench runs/schedule-v4/workbench --out runs/guided-annotation-new
.venv\Scripts\python.exe tools/serve-annotation-workbench.py runs/guided-annotation-new 8828
.venv\Scripts\python.exe tools/guided-annotation.py check --batch runs/guided-annotation-new --answers runs/my-guided-answers.json --out runs/my-guided-draft.json
```

匯入不是人工正確性評分，也不批准資料凍結或訓練。錯誤批次、時間／欄位、帶猜測的不確定回答，以及改過的素材包都必須拒收；錯框與未填題保持 pending。

本輪驗證結果：完整 pytest 152 項通過，179.56 秒，JUnit 位於 `tmp/guided-annotation-tests.xml`；mypy 2 檔通過。新引導頁、既有草稿與練習頁的 3 個 Node 檢查均通過。Python 新案例包含前導零、每項判讀者、錯框／未填保留、錯誤來源、時間、不確定答案、素材異動及拒絕覆寫。另以交付包執行答案核對，確認 7 檔 checksum 與頁面來源相符，空白提交保持 5 題 pending、0 張整圖確認。

複核後另修正共用草稿驗證的 JSON 欄位順序問題，相關 5 項 pytest 重跑通過，1.79 秒；Node 草稿檢查及 mypy 亦通過。整合測試直接將 Python `check_submission` 的磁碟輸出交給頁面的 `validateDraft`，確認可匯入，且異動來源、缺欄位、額外欄位或影格順序不同仍拒收。沒有改寫歷史 workbench 匯出包；修正位於原始模板，後續匯出才會套用。使用者繼續使用新引導頁，不必回舊頁匯入。

瀏覽器實測 5 個框選及原始像素放大、正常與不確定填答、錯框回報、重新開啟後續填、可見 JSON、複製與匯入。交付頁重新核對為 0/5，沒有保存測試人員的答案。伺服器只聽取 `127.0.0.1:8828`。

## Spec

獨立複核確認 5 個框與來源相符、沒有預填答案，數字與每項判讀者可保存；不確定／錯框不會被升格為整圖驗收，凍結協定與 gate 保持原狀。複核提出交付文件仍引用 v1 的問題，已同步為 v2 的目錄、批次及匯出包 ID，沒有剩餘阻擋。

## Standards

獨立複核找到 Python 排序 JSON 欄位後，既有工作頁將相同來源誤判為不符的相容性問題。已在共用 `validateDraft` 修正，保留來源值與影格順序檢查，補上真正的跨工具匯入測試。複核確認阻擋解除，沒有其他硬性規範或 heuristic 發現。
