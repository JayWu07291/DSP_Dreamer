# Raw 10 分鐘對照，2026-09-06

run `20260906T151649Z`，probe 0.1.15。11,998 幀的 byte count、連續 offsets、總檔案大小與 summary 相符，完整 raw 檔案 SHA-256 已保存於 verification JSON。這是 raw 檔案一致性檢查，不是另一個壓縮往返測試。

600.202 秒，有效 19.9899 Hz，scheduler drops 2／12,000，0.01667%。GPU readback error、in-flight drop、writer drop 都是零，queue 最高 1 幀，沒有持續累積。10 分鐘對照門檻通過，不宣稱它是 30 分鐘測試。舊 summary 的總判定仍因未執行控制注入而未通過，原始 summary 保持不變。

影像 10.2980 GiB，加 events 為 10.3184 GiB。修正後遊戲程序 RSS 取樣峰值 4,503,576,576 bytes，約 4.19 GiB。這包含 DSP、Unity 與 probe，不能當成 recorder 額外占用。raw 沒有 encoder process，因此 encoder RAM=-1 是不適用。

使用者確認「操作相近，沒有感覺差異」，對應與 FFV1 相近的面板操作、移動、建造與拆除及流暢度比較。事件包含 50 次面板開啟與關閉、49 次建造、2 次拆除。抽查起訖、科技樹、背包、合成器、機甲面板、建造與滑鼠大幅移動時畫面，未見 probe overlay 或方向／色彩異常，游標合成 11,998／11,998。預覽索引已保存，PNG 留在本機 out。

## 相同長度區間

比較兩次 session 的前 600 秒，詳見 `comparison.json`。人工操作相近，但不是逐幀相同的工作負載。錄製器版本 0.1.14／0.1.15 的差異為 RAM 量測 API；不能把全部 CPU 差值歸因於 codec。

| 指標，前 600 秒 | FFV1 | raw |
| --- | ---: | ---: |
| 寫入幀數 | 11,992 | 11,998 |
| 時間窗內有效 Hz | 19.9867 | 19.9967 |
| scheduler gap 幀數 | 8 | 2 |
| writer median ms | 9.86 | 0.33 |
| writer p99 ms | 30.84 | 0.53 |
| DSP 程序平均 CPU cores | 2.174 | 1.765 |
| encoder 平均 CPU cores | 0.525 | 不適用 |
| DSP RSS 取樣峰值 | 缺測 | 4.19 GiB |

時間窗有效 Hz 分母固定 600 秒；raw 全 run 摘要分母包含停止排空的 600.202 秒，因此與摘要略有差異。comparison 的 writer queue 是 writer 取出當前 packet 後的深度，不等於 producer 記錄的全 run max queue。兩次每秒 queue 取樣均未持續累積。

raw 寫入明顯更快，FFV1 仍達到擷取門檻並減少影像容量。前次完整 FFV1 run 同幀數節省 72.1%，不能用這兩份不同時長、不同遊玩內容的總容量直接相除。

## 下一步

已備份 raw 設定並準備 FFV1、20 Hz、300 秒，使用同一版 0.1.15 補量測遊戲與 encoder RAM。此次補測只提供短程資源證據，不追溯填補前次 30 分鐘缺失的記憶體曲線。

原型的 raw 對照已完成；FFV1 RAM 補測、compiled dataset／compiler 暫存併存峰值、正式錄製器工時與使用者最終取捨仍待完成。本票不結案，既有 evidence 不刪除。
