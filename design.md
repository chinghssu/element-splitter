# 設計文件 — element-splitter

## 技術選型

| 項目 | 選擇 | 理由 |
|---|---|---|
| 語言 | Python 3.10+ | 使用者指定，且 SAM 官方生態在 Python |
| SAM 實作 | [MobileSAM](https://github.com/ChaoningZhang/MobileSAM)（`mobile_sam` pip 套件） | 跟 auto_ppt 現有選型一致（輕量、CPU 可跑），API 跟官方 `segment-anything` 幾乎相容 |
| 推論後端 | PyTorch（CPU） | `mobile_sam` 官方套件就是包 PyTorch，不用自己轉 ONNX |
| GUI | Tkinter + Pillow | Python 內建、零額外系統依賴，滑鼠拖曳畫框用 `Canvas` 綽綽有餘 |
| 影像處理 | Pillow + numpy | 裁切、alpha 合成、棋盤格底圖 |

不用 ONNX Runtime（跟 auto_ppt 的 `mask-sam.mjs` 不同）：這裡是全新獨立小工具，直接用
`mobile_sam` 官方 PyTorch checkpoint 最簡單，少一道轉換流程。CPU 推論一張圖幾秒可接受。

## 檔案結構

```
element-splitter/
├── requirement.md
├── design.md
├── task.md
├── requirements.txt          # torch, torchvision, mobile_sam, pillow, numpy
├── models/
│   └── SOURCES.json          # checkpoint 下載網址 / sha256 / 授權（不進版控的是權重本身）
├── doctor.py                 # 檢查/下載 MobileSAM checkpoint
├── sam_engine.py             # 包裝 MobileSAM：載入模型、算 embedding、box 推論、遮罩聯集
└── app.py                    # Tkinter GUI 主程式
```

## 核心流程

1. **載入圖片**（`app.py`）：Open File 對話框選圖 → Pillow 讀取 → 顯示在 `Canvas` 上
   （超過視窗大小時等比縮小顯示，但所有座標運算都換算回原圖像素）。
2. **計算 embedding**（`sam_engine.py`）：呼叫一次 `predictor.set_image(image)`。這是貴的
   一步，只在「換圖片」時做一次，同一張圖片切多個元素共用同一份 embedding
   （跟 `mask-sam.mjs` 的 per-source-file 快取是同樣的道理，只是這裡快取活在記憶體裡，
   不用另外做磁碟快取）。
3. **畫框**：使用者在 `Canvas` 上拖曳畫矩形。一個「元素」可以累積多個框（對應 requirement
   裡「多框聯集」需求），畫好的框都疊加顯示在圖上，並列在側邊清單可個別刪除。
4. **執行 SAM**（按下「切這個元素」）：
   - 每個框各自呼叫 `predictor.predict(box=box_xyxy, multimask_output=False)`
     （單一輸出，跟 auto_ppt 的選擇一致：box 提示下歧義小，不需要 multi-mask 候選）。
   - 多個框的布林遮罩做 `np.logical_or` 聯集。
   - 聯集遮罩的最小外接框（或所有輸入框的聯集框）決定輸出裁切範圍。
5. **預覽**：裁切區域內，RGB 取原圖像素（不歸零，跟 `mask-sam.mjs` 的第二個設計原則一致，
   避免補洞變黑），alpha 用遮罩，疊在棋盤格底圖上顯示。
6. **匯出**：Save As 對話框輸出 RGBA PNG。
7. **繼續切下一個元素**：清空目前框清單，embedding 不變，回到步驟 3。

## GUI 版面（單視窗）

```
┌─────────────────────────────────────────────┬───────────────┐
│                                               │ 目前框：       │
│               圖片畫布（可畫框）                │  □ box 1  [x] │
│                                               │  □ box 2  [x] │
│                                               │               │
│                                               │ [ 執行 SAM  ] │
│                                               │               │
│                                               │  預覽（去背）  │
│                                               │               │
│                                               │ [ 另存 PNG ]  │
│                                               │ [ 下一個元素 ] │
└─────────────────────────────────────────────┴───────────────┘
[開啟圖片]                                    狀態列：模型載入中/就緒/耗時
```

## 錯誤處理原則

- checkpoint 缺失 → 明確訊息「請執行 `python doctor.py --fix`」，不要在 GUI 裡默默下載
  （跟 auto_ppt 的 `doctor.mjs` 慣例一致：安裝是顯式動作）。
- 框畫在圖片外 / 框太小（< 4px）→ 直接擋在畫框階段，不送進模型。
- 遮罩結果全空（SAM 找不到東西）→ 預覽區顯示「沒切到東西」文字，不當成程式錯誤。

## 不做的事（呼應 requirement 的非目標）

- 不做磁碟 embedding 快取、不做批次資料夾處理、不做點選提示模式。
