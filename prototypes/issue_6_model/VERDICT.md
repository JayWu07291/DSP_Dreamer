# 原型結論草案

我建議把下列設定帶入可執行規格：

| 項目 | 建議設定 |
| --- | --- |
| 輸入 | 原生 640×360 RGB，保持 16:9，不縮放、不補邊 |
| 因果 tokenizer | 20×20 影像區塊，形成 32×18 網格；64 個潛在 tokens；32 維 bottleneck；模型寬度 512；4 層因果時間 attention |
| 互動動態模型 | 模型寬度 512；8 個 blocks；8 個 attention heads；8 個 register tokens；每 4 個 blocks 使用一次時間 attention |
| 時間脈絡 | 10 Hz 下使用 64 steps，相當於 6.4 秒 |
| 訓練批次 | 一般使用 32 steps，定期使用 80 steps；microbatch 2；梯度累積 8 次；effective batch 16 |
| Shortcut forcing | 使用 x-prediction；最小 step 1/4；bootstrap step 1/2；推理使用 4 次 forward passes；正式實作把過去脈絡設為 signal level 0.1 |
| 代理輸出 heads | 17 維任務條件；單向 agent cross-attention；MTP distance 8；17 個 binary controls；121 類滑鼠動作；3 類滾輪動作；symexp twohot reward |
| 代理資料混合 | 50% uniform sequences 計算 dynamics loss；50% 任務相關片段計算 policy 與 reward loss |
| 想像訓練 | 每個 context 啟動一條 rollout；rollout 內固定 task；horizon 15；凍結 tokenizer 與 dynamics；`gamma=0.997`；`lambda=0.95`；PMPO `alpha=0.5`；reverse KL `beta=0.3` |

## VRAM 數字代表什麼

`peak_allocated_gib` 與 `peak_reserved_gib` 來自 PyTorch 的 CUDA memory statistics，只計算這個 Python 行程。它們不是整張顯卡的總用量，也不包含遊戲、瀏覽器、桌面合成器與其他程式占用的 VRAM。

原型另外每 100 ms 呼叫一次 `nvidia-smi`。`whole_device_vram.peak_used_gib` 是整張顯卡在該階段取樣到的最高用量，包含 PyTorch、Windows 桌面與當時其他程式。短於 100 ms 的瞬間尖峰仍可能漏掉，所以 PyTorch 行程容量仍應以 `peak_reserved_gib` 為準。

## RTX 5070 實測

第一次執行沒有開啟 DSP。測試開始前，`nvidia-smi` 顯示整張顯卡已使用 3.194 GiB，空閒 8.470 GiB。

| 階段 | PyTorch 已配置峰值 | PyTorch 保留峰值 | 整張顯卡取樣峰值 |
| --- | ---: | ---: | ---: |
| 世界模型預訓練 | 4.161 GiB | 4.895 GiB | 8.138 GiB |
| Agent finetuning | 1.557 GiB | 1.652 GiB | 4.891 GiB |
| Imagination training | 1.300 GiB | 1.430 GiB | 4.663 GiB |

世界模型預訓練是容量基準。整卡峰值 8.138 GiB 距離 CUDA 可用總量 11.940 GiB 尚有 3.802 GiB。這個數字來自全解析度合成批次，包含 48,202,736 個可訓練參數、BF16 中間 activation、梯度、activation checkpointing，以及執行一次 AdamW update 後配置的 optimizer states。

第二次執行時已開啟 `DSPGAME.exe` 與載入遊戲行程內的 Prototype 錄製器。測試開始前整卡已使用 5.633 GiB，空閒 6.031 GiB。

| 階段 | PyTorch 已配置峰值 | PyTorch 保留峰值 | DSP 開啟時整卡峰值 | 峰值剩餘 |
| --- | ---: | ---: | ---: | ---: |
| 世界模型預訓練 | 4.161 GiB | 4.895 GiB | 10.579 GiB | 1.361 GiB |
| Agent finetuning | 1.557 GiB | 1.652 GiB | 7.337 GiB | 4.603 GiB |
| Imagination training | 1.300 GiB | 1.430 GiB | 7.119 GiB | 4.821 GiB |

三個階段都完成，沒有發生 OOM。世界模型預訓練只剩 1.361 GiB，不符合至少保留 2 GiB 的安全線，而且測試仍未納入 LPIPS、真實資料 loader、CUDA compilation workspace 與正式紀錄工具。

本專題應把工作流程分開。錄製與閉迴路評估需要 DSP；世界模型預訓練與 agent finetuning 使用離線資料，不需要同時開啟遊戲。執行這兩個訓練階段前應關閉 DSP。若確實需要在 DSP 開啟時訓練，先把 microbatch 降為 1，並在 gradient accumulation 中交替抽取 uniform 與任務相關片段，不先犧牲 640×360 畫面。

## 仍待驗證

64 個 latent tokens 是否足以重建 DSP 最小的圖示與文字，這次 synthetic smoke test 無法回答。完整訓練前應使用真實錄影片段比較 64 與 96 個 latent tokens 的 reconstruction quality。

原型讓每條 imagined rollout 固定一個 task。Dreamer 4 沒有交代 imagination 期間是否切換 task。第一版先固定 task 較容易核對 reward 語意；rollout 途中切換 task 留作後續消融實驗。
