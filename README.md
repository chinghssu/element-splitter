# element-splitter

畫框、跑 MobileSAM、把圖片裡的元素切成透明 PNG 的小工具。跟 `auto_ppt` 專案完全獨立。

## 安裝

```bash
pip install -r requirements.txt
python doctor.py --fix   # 下載 MobileSAM checkpoint（約 40MB）
```

`doctor.py`（不加 `--fix`）可以隨時拿來檢查環境缺什麼。

## 使用

```bash
python app.py
```

1. 「開啟圖片」選一張 PNG/JPG。
2. 在畫布上拖曳畫框，框住想切的元素。同一個元素可以畫多個框（例如主體 + 被切開的細長
   部位或色差較大的貼紙區塊），按「執行 SAM」時會把所有框的遮罩做聯集。
3. 右側會即時預覽切出來的去背結果（棋盤格底）。
4. 「另存 PNG」存成透明背景圖檔。
5. 「下一個元素」清空目前的框，繼續在同一張圖上切下一個元素（圖片的 embedding 只算一次，
   不用重新載入）。

## 已知限制

- 只支援 box 提示，不支援點選提示。
- 遇到顏色/紋理跟主體差很多的部位（貼紙、半透明包裝內可見的物體）常會被 SAM 當成獨立
  區塊排除掉，需要手動多畫一個框把它補進聯集——這是 SAM box 提示的已知行為，不是這個
  工具的 bug。
- 沒有磁碟 embedding 快取、沒有批次處理，見 `requirement.md` 的非目標。
