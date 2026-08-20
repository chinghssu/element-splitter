# element-splitter

用 MobileSAM 把平面圖片（插畫、商品合照、截圖）裡的元素切成透明 PNG 的小工具，也可以
用 LaMa 把切走素材後留下的洞補起來——類似 Canva「移動素材、底色自動補上」的效果。

跟其他專案完全獨立：獨立 Python、獨立 repo、不共用程式碼。

Other languages: [English](README.md)

## 安裝

```bash
pip install -r requirements.txt
python doctor.py --fix   # 下載 MobileSAM checkpoint（約 40MB）
```

`doctor.py`（不加 `--fix`）可以隨時拿來檢查環境缺什麼。

背景修補功能第一次使用時會額外下載約 196MB 的 LaMa checkpoint（由 `torch.hub` 快取，
不歸這個專案的 `models/` 管）。

## 使用

```bash
python app.py
```

1. **Open Image**（開啟圖片）選一張 PNG/JPG。
2. 在畫布上拖曳畫框，框住想切的元素。同一個元素可以畫多個框（例如主體 + 凸出的細長
   部位，或色差較大的貼紙/標籤區塊），按 **Run SAM**（執行 SAM）時會把所有框的遮罩
   做聯集。
   - 滾輪可以縮放來精確對邊界；選取一個框後，側邊面板的 x0/y0/x1/y1 數值欄位也可以
     逐像素微調。
3. 側邊面板會即時預覽切出來的元素（透明 PNG 疊在棋盤格底上）。**Save Element PNG**
   （另存素材 PNG）存成透明背景圖檔。
4. **Repair Background (remove boxed area)**（修補背景）用 LaMa inpainting 把框選範圍
   的素材從原圖移除，結果會顯示在主畫布上。滿意的話按 **Save Background PNG**（另存
   背景 PNG）存檔。
   - 這裡刻意用「畫的框」本身當挖除範圍，不是 SAM 的精細遮罩，原因見下面「已知限制」。
5. **Next Element**（下一個元素）清空目前的框，繼續在同一張圖上切下一個元素（圖片的
   SAM embedding 只算一次，不用重新載入）。

## 已知限制

- 只支援 box 提示，不支援點選提示。
- 遇到顏色/紋理跟主體差很多的部位（貼紙、半透明包裝內可見的物體）常會被 SAM 當成獨立
  區塊排除掉，需要手動多畫一個框把它補進聯集——這是 SAM box 提示的已知行為，不是這個
  工具的 bug。
- **修補背景刻意用「畫的框聯集」而不是 SAM 的精細遮罩當挖除範圍。** 早期測試發現，直接
  把 SAM 精細遮罩餵給 LaMa，會在 SAM 排除掉的低對比部位留下一小塊完全沒被修補的原始
  素材——素材永遠不會完全消失。用矩形多挖一點背景是安全的（LaMa 補得動），但漏挖到
  素材本身不行。
- **記憶體**：LaMa 用的 Fourier Convolution 是全域運算，記憶體會隨圖片解析度大幅膨脹。
  實測在 MacBook Air M2（16GB RAM）上，直接對一張 1672×941 的圖跑 inpainting，peak
  memory footprint 衝到約 19.5GB——超過實體記憶體，會造成嚴重拖慢甚至被系統砍掉行程。
  為了安全，`inpaint_engine.py` 一律把圖片複製一份縮到長邊 1024 再跑 LaMa（實測峰值約
  8.3GB），推論完只把修補結果貼回原始解析度圖片的挖除範圍，其餘地方維持原始像素，
  修補範圍以外的畫質不受影響。
- 沒有磁碟 embedding 快取、沒有跨檔案的批次處理，見 `requirement.md` 的非目標。

## 授權

Apache License 2.0 — 詳見 [LICENSE](LICENSE)。
