# 第十五批錄製核對

2026-09-21，本回為 success／valid，約 5 分 35 秒；6,699 個轉移中 6,695 個有效，回合內沒有未知控制。16 項任務全部取得合法 active 正例，不需重錄。

## 驗證組任務配額已滿

本批屬於 validation，開始拆解、手動冶煉、熔爐接線與矩陣科技供料四項剩餘缺口均由 2／3 補到 3／3。其餘 12 項各達 4／3，validation 的 16 項任務正例配額全部達標。

Train 與 offline-test 計數不因本批增加。Train 只剩開始拆解為 15／20，缺 5 回；其餘 15 項已達 20 回。Offline-test 仍以開始拆解缺 3 回為最大缺口。

第十四批封存摘要加上本批唯一來源後，完整有效回合合計 train 34、validation 4、offline-test 2。剩餘回合數的理論下限為 train 5、validation 0、offline-test 3，合計 **8 回**。這是封存報告合計，總索引與覆蓋 gate 尚未重算；validation 任務配額達標不代表人工標註或模型品質驗證完成。

## 第十六批：三回合

依原登錄順序切回 train 組，維持目前操作順序：

1. 拆完登陸艙、拿到掉落物，再開科技樹。
2. 電磁學完成後，先鐵礦採礦機、再銅礦採礦機，接著冶金供料。
3. 先供齊製造科技研究材料，再完成最後一條熔爐自動供料線。不必等製造科技研究完成才接線。
4. 確認磁線圈產線已自動產出，再接通電路板產線。

按 F8 開始；第一、第二回合成功後各按 F9 重載，第三回合成功後按 F8 結束，等發布完成。回覆「第十六批三回合已錄好」。不需重啟遊戲、F6 或重新校正。

若後續正例均有效，原安排為第十六批 train 3 回、第十七批 train 2 回、第十八批 offline-test 3 回，共 8 回。仍逐批核對，本次只交付第十六批設定；後續數量依實際缺口決定。

## 證據與設定

本回共有 6,700 張影像。新來源目錄為 `runs/live/73512c84-a3fc-4ef4-9fcc-2e6d3717c11d.source.evidence` 及相鄰 `.source.dataset`。Dataset artifact 為 `228dd259-cf5e-4c49-9875-18dfdad55a5d`，目錄名稱不等於 artifact ID。

原始檔 checksum、正式 Dataset／ModelView、單批 TrainingIndex、保留 trial 隔離與核准指紋均通過。新資料驗證與單批索引耗時 18.01 秒，歷史 Dataset／ModelView 開啟數為 0。未讀舊 RGB、重建總索引或評估包；原因診斷只讀本回新來源 metadata、事件及轉移表，16 項正例數均與單批索引一致。

收件、診斷、設定備份與套用收據位於 `runs/catalog-v4/recording-review-20260921-batch15`，可追蹤摘要見 [機器可讀報告](recording-batch15.json)。共保留 21 份唯一來源身分；第六批以後仍列入待整合來源，最新完整總索引與評估輸入仍停在第五批。

第十六批 plan index 15，seeds 230045／230046／230047，manifest `e32ed0bf7eae4042b1d1507ae3b845c49eef0bb4e5fc90352bdbb8bbbdd16af9`，bucket 42 屬於 train。僅更新三個 seeds，設定已備份並讀回核對，SHA-256 為 `80af0828d09453186d535ca86c0498b038e10a184619a01246c0e17cfcae9d03`。

Starting Save、輸入設定、錄製器 DLL、指紋、校正及 Diagnostics=false 均與核准版本一致。action_catalog_v4、任務排程與凍結協定未變。資料未凍結、未授權訓練。
