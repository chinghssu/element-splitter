# 任務清單 — element-splitter

- [ ] T1 專案骨架：`requirements.txt`、目錄結構、`.gitignore`（排除 `models/*.pt`、`venv/`）
- [ ] T2 `models/SOURCES.json` + `doctor.py`：MobileSAM checkpoint 下載網址、sha256、授權；
      `python doctor.py` 只檢查，`--fix` 才下載
- [ ] T3 `sam_engine.py`：載入 MobileSAM、`set_image` embedding 快取、單框推論、多框聯集、
      裁切邏輯（RGB 取原圖不歸零）
- [ ] T4 `app.py` 基本骨架：開啟圖片、Canvas 顯示（含縮放座標換算）
- [ ] T5 `app.py` 畫框互動：拖曳畫矩形、框清單顯示與刪除
- [ ] T6 串接 `sam_engine`：執行 SAM、預覽去背結果（棋盤格底）、狀態列訊息
- [ ] T7 匯出 PNG（Save As）與「下一個元素」重置流程
- [ ] T8 錯誤處理：checkpoint 缺失、框太小/在圖外、空遮罩
- [ ] T9 手動驗收：找一張 3~5 元素的測試圖，逐一切出並檢查邊緣品質（對照 requirement 驗收標準）
- [ ] T10 簡短 README：安裝步驟（`pip install -r requirements.txt`、`python doctor.py --fix`）、
      啟動方式（`python app.py`）
