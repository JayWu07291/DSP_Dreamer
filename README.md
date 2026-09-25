# DSP Dreamer

在《戴森球計畫》前期受控場景中，研究以低階鍵鼠動作學習多個微任務的 Dreamer 4-inspired 代理。

目前已完成錄製器、轉移資料集、10 Hz 模型視圖、固定 split 與評估協定。Issue #22 的資料及人工標註已凍結，2026-09-25 逐條複核後結案。詳見 [Issue #22 完成核對](docs/issue-22-completion.md)。

Issue #24 的 [tokenizer 訓練、checkpoint 恢復與重建評估工具](docs/tokenizer.md)已完成五項工程驗收。64／96-token 各四次對照更新及 200 圖評估已完成；人工判讀兩組各 0／15 正確、無缺判，重建品質 gate 均為 failed。四次更新不能支持收斂或容量優劣結論，正式 dynamics 訓練仍須等待重建 gate 通過。正式 v1 維持 64 latent tokens，詳見 [驗證紀錄](docs/issue-24-validation.md)。

Issue #25 的 [dynamics 訓練、恢復與配對預測評估工具](docs/dynamics.md)已完成修訂後五項工程驗收，逐項證據見[驗證紀錄](docs/issue-25-validation.md)。工程測試使用合成 fixtures；正式 A／B 訓練與實際品質驗收由 #31 執行，第一階段 B 仍須先通過重建 gate，尚無正式預測品質結果。

## 專案結構

| 路徑 | 用途 |
| --- | --- |
| `dsp_dreamer/` | Python 資料、動作、進度、模型視圖與評估協定 |
| `src/DSPDreamer.Recorder/` | DSP 的 Windows Unity 錄製與控制插件 |
| `tests/` | 持續使用的 Python、C# 與標註介面回歸測試 |
| `tools/` | 錄製、部署、校正、資料索引與標註工具 |
| `protocols/` | 已凍結的評估協定、trial manifests 與版本 |
| `docs/` | 目前狀態、資料位置、領域決議與研究筆記 |
| `data/` | 本機正式資料、凍結評估包與校正檔，不納入 Git |
| `papers/` | 持續使用的參考論文，保留本機 |
| `Assembly-CSharp/` | DSP 反編譯參考檔，保留本機 |
| `reference_codes/` | 外部參考程式碼，保留本機 |

歷史錄像、舊資料集、標註頁、一次性腳本與測試報告已移出 repo，47 個封存包共約 380 GiB 保存在 G 槽。2026-09-25 使用者確認 Google Drive 同步完成，本機暫存副本已清理；整理紀錄與一次性腳本也已移到封存資料夾。位置及還原方式見 [封存紀錄](docs/archive.md)。Git 歷史保留。

## 正式資料

24 份正式資料集約 158.5 GiB，位於 `data/datasets/<artifact_id>/`。共有 47 個完整有效回合，train 38、validation 4、offline-test 5；各微任務的 20／3／3 個正例配額已滿足。

Issue #23 的[交付核對與覆蓋統計](docs/issue-23-status.md)已完成。資料覆蓋與凍結身分通過，六段恢復示範已人工確認；歷史工時保持未知，依使用者核准的[本批驗收例外](protocols/evaluation-v2.0.1-issue23.md)完成交付。

- `data/training-index.json`：原有已凍結索引。
- `data/evaluation/`：200 張重建圖片的名單、四類各 50 段預測序列、annotations、baseline 與資料凍結紀錄。
- `data/prediction-candidates.json`：241 個完整人工候選。
- `data/runtime/calibration.json`：遊戲插件目前使用的校正檔。

搬移只改變檔案位置，資料內容、artifact ID、split、baseline 和固定抽樣保持原樣。完整位置對照見 [data-catalog.json](docs/data-catalog.json)，使用方式見 [正式資料位置](docs/data-layout.md)。原始錄製證據仍保存在封存中，需要重新編譯時可取回。

## 環境與工具

使用 Windows、Python 3.12、.NET SDK，以及已安裝 DSP 的 Unity Mono 組件。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e . pytest==8.4.2 mypy==1.18.2
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj
```

插件固定 net472、Windows x64、BepInEx 5.4.23.5 及 HarmonyX 2.9.0。遊戲預設位置為 `E:\Steam\steamapps\common\Dyson Sphere Program`；需要時以 MSBuild 的 `DSPRoot` 屬性指定。遊戲組件不隨插件封裝。

錄製與資料編譯使用 FFmpeg 6.1.1，SHA-256 必須為 `04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00`。這是既有錄製契約，不是本次封存的額外檢查。

目前控制契約為 `action_catalog_v4`／21 維；B 是建築模式，X 是拆除模式。20 Hz 錄製轉為 10 Hz 模型視圖。採礦優先的任務排程見 [ADR-0001](docs/adr/0001-task-schedule-v4.md)，控制版本見 [ADR-0002](docs/adr/0002-build-mode-control.md)。遊玩材料及配方筆記見 [gameplay-reference.md](docs/gameplay-reference.md)。

常用入口：

```powershell
.venv/Scripts/python.exe -m dsp_dreamer --help
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy dsp_dreamer
```

`tools/deploy-recorder.ps1` 用於部署；`tools/verify-control.py` 用於校正。重新部署會改變插件指紋，需要重新核准；本次整理沒有重新部署。插件校正路徑已改為 `data/runtime/calibration.json`，校正內容、核准值及其他設定未變。

## 評估協定

[協定 v2](protocols/evaluation-v2.md)固定評分、標註、baseline、seeds、門檻及 offline-test 揭露順序。[版本檔](protocols/evaluation-v2.json)與 [10 development／30 final manifests](protocols/evaluation-trials-v1.json)保留原始位元組。準備工具須明確傳入 `--protocol protocols/evaluation-v2.json`。

資料凍結完成不表示模型品質通過，也不授權跨過訓練 gate。40 份固定 trial 的輸入設定 hash 與目前示範環境仍有差異，正式遊戲試驗前須處理。v1 歷史重現使用當時的程式版本，例如 `5c13232`。
