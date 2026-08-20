# 設計文件 — element-splitter

## 技術選型

| 項目 | 選擇 | 理由 |
|---|---|---|
| 語言 | Python 3.10+ | 使用者指定，且 SAM 官方生態在 Python |
| SAM 實作 | [MobileSAM](https://github.com/ChaoningZhang/MobileSAM)（`mobile_sam` pip 套件） | 跟 auto_ppt 現有選型一致（輕量、CPU 可跑），API 跟官方 `segment-anything` 幾乎相容 |
| 推論後端 | PyTorch（CPU） | `mobile_sam` 官方套件就是包 PyTorch，不用自己轉 ONNX |
| GUI | PySide6 + Pillow | 改自 Tkinter：`QGraphicsView`/`QGraphicsScene` 支援滾輪縮放與逐像素數值微調框，畫框更精確；框是獨立場景物件，刪除不會有殘影 |
| 影像處理 | Pillow + numpy | 裁切、alpha 合成、棋盤格底圖 |
| 背景修補 | [LaMa](https://github.com/advimman/lama)（`simple-lama-inpainting` pip 套件） | 素材切走後補洞，模擬 Canva「移動素材自動補底」效果；套件自動下載 TorchScript 版 checkpoint（約 196MB），CPU 可跑 |

**GUI 從 Tkinter 換成 PySide6 的教訓**：如果環境裡同時裝了 PyQt6，`PIL.ImageQt` 的 Qt binding
自動偵測邏輯（優先用已 import 過的，否則預設先試 PyQt6）會在 import 順序不對時搶先載入 PyQt6
的 `QtCore.framework`，跟後面才 import 的 PySide6 撞名，macOS dyld 直接 crash。修法是把
PySide6 的 import 排在 `from PIL.ImageQt import ImageQt` 之前，不需要動任何環境變數。

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
├── inpaint_engine.py         # 包裝 LaMa：對完整原圖的遮罩區域補洞
└── app.py                    # PySide6 GUI 主程式
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
8. **修補背景**（按下「修補背景」，`inpaint_engine.py`）：
   - LaMa 只認得「1 通道二值遮罩（255=要補的區域）」，直接把步驟 4 算出的聯集遮罩轉成這個
     格式即可，不用另外處理。
   - inpaint 是對**完整原圖**做，不是對裁切區域——不然補出來的內容會少掉周圍可用的上下文，
     LaMa 需要看到洞外面的紋理才能補得像。
   - `SimpleLama` 模型是惰性載入（第一次呼叫才建立），跟 MobileSAM 分開兩個模型常駐記憶體，
     沒有互相依賴，也不共用 `SamEngine` 的 embedding 快取。
   - 跟「執行 SAM」同一套兩段式流程：先跑推論、把結果顯示在預覽區（使用者要先看到
     「挖除後長怎樣」再決定存不存），按「另存修補結果 PNG」才真的寫檔——不是按一顆鈕
     就直接跳存檔對話框、看不到結果就存掉。
   - 結果另存成一張跟原圖同尺寸的 PNG，不會覆蓋原圖、也不會自動接回畫布繼續編輯
     （呼應 requirement 的非目標：這版不做「切走再貼到別處」的完整合成流程）。

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
│                                               │ [ 修補背景並另存 ] │
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
