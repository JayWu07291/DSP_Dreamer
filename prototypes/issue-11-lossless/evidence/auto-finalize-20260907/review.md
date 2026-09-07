# 錄製後自動合併與清理

使用者明確要求將已驗證的合併流程接到錄製結束，並自動清理多餘資料。0.1.17 在 `FinishProbe` 關閉事件與影像 writer 後，啟動無視窗 Python worker。合併期間禁止新錄製，worker 不依賴 Unity 持續更新才能完成。

worker 先完整解碼原始分段、核對事件與索引，再合併並重驗單一影片。最終 manifest 記錄輸出 checksum、原始 summary、來源段封存資訊、驗證報告及可清理檔案的 checksum。發布三個資料檔後才原子發布 manifest；事件檔保持原始 bytes。清理前重新核對四檔及所有尚存來源 checksum，只移除本 run 清單內相符的檔案。路徑驗證拒絕越界、符號連結與 junction，不使用 recursive delete。

以一分鐘原始錄製的獨立副本做整合測試，1,198 幀全數通過，包含：

- 完成發布後清理兩個檔案即受控中斷，已驗證最終四檔仍可讀。
- 修改尚未清理的來源一個 byte，重試拒絕，其他尚存來源均未刪除。
- 還原該測試 byte 後重試，清理成功，目錄恰剩四檔。
- 再次執行已完成 run，仍只有四檔。
- 模擬部分資料檔發布、manifest 尚未發布，重試完成發布與清理。
- 模擬可用空間不足，拒絕開始合併，來源 hashes 全部不變。
- 所有原始實驗檔案逐一 hash 核對，未修改。

報告見 [checks.json](checks.json)。這是受控故障注入，不是斷電持久性保證。最初測試工具選到空的 stderr 當竄改目標，修正為非空 JSON 後完整重跑通過；該失敗副本仍留在 ignored out 供追溯。

部署前 build 通過，0 errors、0 warnings。已部署 DLL 與建置產物 SHA-256 一致，啟用 `AutoFinalize=true`，保留 20 Hz／60 秒測試設定。備份位於 `out/deployment-backup-20260907T035143Z/`。另直接呼叫已部署 worker 處理 workspace 副本，確認部署檔能完整執行。

仍需一次新遊戲錄製確認 Unity 停止事件與背景程序在實際遊戲環境的銜接。正式版還需串流化大量 metadata 的處理及完整故障／資源驗收；本次更新屬於原型分支，未合併 main。
