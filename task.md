# 任務清單 — element-splitter

- [x] T1 專案骨架：`requirements.txt`、目錄結構、`.gitignore`（排除 `models/*.pt`、`venv/`）
- [x] T2 `models/SOURCES.json` + `doctor.py`：MobileSAM checkpoint 下載網址、sha256、授權；
      `python doctor.py` 只檢查，`--fix` 才下載
- [x] T3 `sam_engine.py`：載入 MobileSAM、`set_image` embedding 快取、單框推論、多框聯集、
      裁切邏輯（RGB 取原圖不歸零）
- [x] T4 `app.py` 基本骨架：開啟圖片、畫布顯示
- [x] T5 `app.py` 畫框互動：拖曳畫矩形、框清單顯示與刪除
- [x] T6 串接 `sam_engine`：執行 SAM、預覽去背結果（棋盤格底）、狀態列訊息
- [x] T7 匯出 PNG（Save As）與「下一個元素」重置流程
- [x] T8 錯誤處理：checkpoint 缺失、框太小/在圖外、空遮罩
- [x] T9 手動驗收：用實際商品合照跑過 headless 驗證，確認多框聯集能補回單框漏切的部位
- [x] T10 簡短 README：安裝步驟、啟動方式
- [x] T11 GUI 從 Tkinter 換成 PySide6：`QGraphicsScene` 管理框物件（修掉殘影 bug）、
      滾輪縮放、框座標數值微調面板
- [x] T12 `inpaint_engine.py`：包裝 `simple-lama-inpainting`，輸入完整原圖 + 遮罩，
      輸出補洞後的完整背景圖（裁回原尺寸，修正 LaMa 內部 pad-to-modulo-8 的偏移）
- [x] T13 `app.py` 加「修補背景並另存」按鈕，串接 `inpaint_engine`；更新
      `requirements.txt`（加 `simple-lama-inpainting`，並把 Pillow 版本衝突處理掉）
- [x] T14 手動驗收：用商品合照測試，發現直接用 SAM 精細遮罩補洞會漏挖到低對比部位
      （麵包本體完全沒被遮罩涵蓋，補完還在原處），改用「畫的框矩形聯集」當挖除範圍後
      素材完整移除，補丁品質堪用（不是無縫，但至少不會穿幫）
- [x] T15 GUI 全面英文化；元素預覽（側邊）跟修補背景預覽（主畫布）分開，避免互相蓋掉；
      「另存 PNG」改名「Save Element PNG」跟「Save Background PNG」對稱
- [x] T16 雙語 README（`README.md` 英文 / `README.zh-TW.md` 繁中，互相連結）、
      `LICENSE`（Apache-2.0，跟 MobileSAM／LaMa 原始授權一致）
- [x] T17 `main.spec`：PyInstaller 打包成 macOS `.app`，內含 MobileSAM checkpoint；
      排除 PyQt5/PyQt6/PySide2 跟 torch hook 帶進來的非必要開發相依（不排除的話
      matplotlib 會拉 PyQt 進來，跟 PySide6 衝突直接打包失敗）；用
      `ELEMENT_SPLITTER_SELFTEST` 環境變數在打包後的執行檔裡實測過 checkpoint
      路徑解析與 `load_image()`，確認可行後移除測試程式碼
