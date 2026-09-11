# Issue #17 封存恢復驗證

2026-09-11。前置 gate 依 #13 的 1,066 幀新實機四檔、來源完整 RGBA 核對與 1,065 筆 compiler 讀回證據確認通過，詳見 [#13 驗證](issue-13.md)。本次新增測試在專用合成來源與正式 C# SegmentWriter 的獨立程序執行，不修改既有實機 evidence。

## 已實作

- C# writer 每 200 幀完成 segment、flush 影片與兩份 NDJSON 後，原子保存檢查點。檢查點包含 metadata 快照、段 checksum、sidecar 前綴長度與 checksum。正常停止的 `SOURCE.json` 保存最終 seal。
- 封存先完整核對來源，再建立本次獨立副本、合併及核對。完成收據先落盤，三份資料檔先發布，manifest 最後以原子 rename 發布。發布後重驗四檔才准許清理。
- 清理先核對全部剩餘清單，再逐檔重驗。拒絕路徑穿越、符號連結與 junction 導向的工作目錄；不遞迴刪除目錄。清單以外檔案保留。
- `finish` 在核對與清理後才執行 compiler。已完成 evidence 與 dataset 可重試且位元組不變。未完成 dataset 需要以新 `compile --out` 重編譯。
- 恢復由最新的可核對前綴產生新 artifact，保留原來源與故障資料。排除起點、檢查點身分、驗證失敗原因及未知尾端範圍寫入 `recovery`，並傳遞至 dataset。缺 final observation 的回合不冒充完整回合。

## 可重跑檢查

```powershell
dotnet restore tests/ArchiveRecovery/ArchiveRecovery.csproj
.\.venv\Scripts\python.exe -m pytest tests/test_archive.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore
```

封存專用測試涵蓋截斷 MKV 尾段、截斷 NDJSON 尾端、來源 seal 不符、合併期間來源變更、低空間、合併失敗、三檔部分發布、manifest 發布前中斷、清理中斷、路徑穿越、Windows junction、清理前來源變更、首段損毀拒絕、非法 lifecycle 拒絕與完成後重試。

完整測試 69 項通過，其中封存專用測試 16 項，耗時 108.02 秒；mypy 檢查 11 個 Python 原始碼檔案無問題；net472 插件建置零警告、零錯誤。

兩項程序終止測試實際終止專用子程序。C# 測試直接使用正式 SegmentWriter，完成第一段後被終止，沒有 `SOURCE.json`；恢復取得 200 幀，正式 compiler 讀回 199 筆轉移。Python archiver 在三個資料檔已發布、manifest 尚未發布時被終止；重試完成四檔核對與清理。原始 partial 目錄缺 manifest 時，compiler 會拒絕。

另以 lifecycle 與 progress v3 資料核對恢復結果，保留原 trial／split、任務進度與 reward，受影響回合標為 `incomplete`，最後轉移不供訓練且 bootstrap mask 為 0。

## 程式規範審查

獨立 Standards 審查未發現書面規範違反或需要修改的 code smell。審查另提到既有 dataset 入口接受 junction；本次不刪除 dataset，也不覆寫既有 dataset 目錄，因此沒有擴大成所有 artifact 的路徑別名禁令。來源清理與 evidence 的路徑檢查已有獨立測試。

## 規格審查

獨立 Spec 審查發現，原恢復流程會在裁切前綴時將非法 episode outcome 覆寫成 `None/incomplete`，使應拒絕的 metadata 通過。已先用回歸測試重現，再讓共用 lifecycle 驗證器先核對原始 outcome、reasons、start、status 與 final ID。檢查點僅允許最後回合仍開啟或 final observation 位於前綴之後；裁切後再次執行普通驗證。複查確認這項缺陷已修正，沒有其他已確認的規格 finding。

## 限制

未測試斷電、OS 當機、磁碟損壞或同時有其他程序惡意修改檔案，不宣稱這些情況下的保證。來源與 evidence 限同磁碟區，依 Windows rename 不覆寫目的檔的語意發布。容量預檢不能保留磁碟配額，執行中仍可能被其他程序用完空間。

舊錄製沒有 seal 時可依既有完整驗證流程封存，但不能使用未核對的 `INCOMPLETE.json` 恢復。未完成段、未通過檢查點的尾端及先前失敗的工作副本保留。最終 evidence 固定四檔，來源與工作目錄可留下空目錄或無關檔案。

本次未部署新 DLL，也未用新版插件執行 DSP 內的長時間錄製。C# 測試證明正式 writer 的檢查點格式與 Python 恢復相容，不取代遊戲內長程吞吐驗收。sidecar 前綴目前在每段結束重新計算 checksum；若長錄製造成 writer 停頓，應改為增量雜湊。
