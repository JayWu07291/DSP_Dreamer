# 第十八批開始前的指紋差異

2026-09-21，按 F8 出現 `Unknown fingerprint`。原因已確認為兩個遊戲音量值變更；新舊 runtime 唯一不同欄位是 `input_settings_sha256`，遊戲與插件 binary hashes、解析度及滑鼠設定均相同。

| 遊戲選項 | 原核准值 | 目前值 |
| --- | --- | --- |
| 音效音量，`SoundEffectVolume` | 95% | 75% |
| 環境音效音量，`AmbientSoundEffectVolume` | 90% | 50% |

錄製器目前對整份 `options.xml` 算 SHA-256，所以音量也會影響指紋。只替換這兩個 XML 值即可逐 byte 重建原核准的選項檔，SHA-256 回到 `f993919fe80b1de22a462800b7a08170042aa39652a59e21435c65518e0a731d`；目前檔案是 `4042dc70500684ab63ebdc08b8b1ceae2aa3eb4ebe8127a7a884ebed191f58be`。

目前拒絕的 runtime fingerprint 是 `a3cc7f50b87107e793cbf4204e60ba7ada1d5c576895bbc1afe5f5bda5c75096`。恢復上述選項後，重建出的 runtime bytes 與既有核准候選檔完全相同，指紋為 `dda0773aa09e441e93120cefbf3e6dd3e5ae887a0760047ba78f8f92465c1dae`，可沿用校正與第十八批 manifest。

## 恢復步驟

請在遊戲選項中將音效音量調回 95%、環境音效音量調回 90%，按套用後再按 F8，即可嘗試開始原定第十八批三回合。前兩回成功各按 F9，第三回成功按 F8 結束。不需重新校正；F8 這次的失敗只記錄錯誤，不會將錄製器鎖定為 failed，因此也不需為這個錯誤重啟遊戲。

若需要降低整體聲音，可用 Windows 音量混音器調整 DSP 音量，避免改寫遊戲選項檔。尚未在遊戲內重試，恢復是否完成要以重新按 F8 的結果為準。

## 核對與保留

以目前安裝 DLL 的 `StartRecording` 指紋檢查 IL 重播，保留原比較、分支與例外，只把原 local／field 讀取替換為捕獲資料參數。命令 `& .\tmp\fingerprint-debug\replay-guard.ps1` 對目前候選檔重現相同的 `InvalidOperationException` 與 SHA-256；傳入原核准候選檔、或由恢復選項重建的候選檔，均通過此檢查。此檢查不會啟動 Unity 或實際錄製。

未修改插件、核准指紋、校正檔、遊戲選項、資料計數、凍結協定或第十八批 seeds。失敗發生於建立錄製來源之前，本次 F8 沒有開始第十八批錄製。仍等待使用者在遊戲中恢復上述兩項選項。

新候選檔、目前選項、精確重建的舊選項、未變更的錄製設定及診斷保存在 `runs/catalog-v4/runtime-options-20260921`；[機器可讀報告](runtime-options-20260921.json) 保留差異與核對身分。所有暫時重播與比對工具集中在 `tmp/fingerprint-debug`，未讀取歷史錄製影像。
