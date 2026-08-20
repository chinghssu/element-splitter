#!/usr/bin/env python3
"""element-splitter — 畫框、跑 MobileSAM、把元素切成透明 PNG 的小 GUI（PySide6）。

    python app.py

框都是獨立的 QGraphicsRectItem，場景座標系跟畫面縮放（滾輪 zoom）無關、就是原圖
像素座標，所以：
  - 拖曳畫框、刪除框，都是對場景物件直接增減，不會有「刪掉/取消後線還留在畫面上」
    這種殘影問題（Tkinter 版舊 bug：拖曳中的暫時矩形沒有跟正式框共用同一個 tag，
    清畫面時只清有 tag 的，暫時矩形就永遠留在畫布上）。
  - 可以滾輪縮放來精確對邊界，還能用右側面板的數值欄位逐像素微調選取中的框，
    比純滑鼠拖曳更精確。
"""
import sys
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from sam_engine import SamEngine

CHECKER = 12  # 預覽棋盤格底圖的格子邊長（像素）
BOX_PEN = QPen(QColor("#00ff88"), 2)
BOX_PEN.setCosmetic(True)  # 線寬不隨 zoom 放大，縮放時邊框不會變得又粗又糊
SELECTED_PEN = QPen(QColor("#ffcc00"), 2)
SELECTED_PEN.setCosmetic(True)


def checkerboard(w, h, size=CHECKER) -> Image.Image:
    img = Image.new("RGB", (max(w, 1), max(h, 1)))
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            light = ((x // size) + (y // size)) % 2 == 0
            px[x, y] = (235, 235, 235) if light else (200, 200, 200)
    return img


class BoxItem(QGraphicsRectItem):
    """一個畫好的框。rect() 就是原圖像素座標（scene 座標系不受 view 縮放影響）。"""

    def __init__(self, rect: QRectF):
        super().__init__(rect)
        self.setPen(BOX_PEN)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, True)
        self.setZValue(1)

    def to_xyxy(self):
        r = self.rect()
        return (r.left(), r.top(), r.right(), r.bottom())

    def paint(self, painter, option, widget=None):
        self.setPen(SELECTED_PEN if self.isSelected() else BOX_PEN)
        option.state &= ~option.state.__class__.State_Selected  # 不要 Qt 內建的虛線選取框
        super().paint(painter, option, widget)


class ImageView(QGraphicsView):
    """圖片畫布：滾輪縮放、拖曳畫框（畫在空白處），點擊既有框則交給 Qt 處理選取。"""

    def __init__(self, on_box_drawn):
        super().__init__()
        self.on_box_drawn = on_box_drawn
        self.setRenderHint(QPainter.Antialiasing, False)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._bg_item = None
        self._drag_start = None
        self._drag_item = None
        self.setDragMode(QGraphicsView.NoDrag)

    def set_image(self, pil_image: Image.Image):
        self._scene.clear()
        self._drag_item = None
        qimg = ImageQt(pil_image.convert("RGB"))
        pix = QPixmap.fromImage(qimg)
        self._bg_item = self._scene.addPixmap(pix)
        self._bg_item.setZValue(0)
        self._scene.setSceneRect(0, 0, pix.width(), pix.height())
        self.resetTransform()

    def wheelEvent(self, event):
        if self._bg_item is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if self._bg_item is None or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        clicked = self.itemAt(event.pos())
        if isinstance(clicked, BoxItem):
            super().mousePressEvent(event)  # 交給 Qt 處理選取／取消選取
            return
        pos = self.mapToScene(event.pos())
        self._drag_start = pos
        self._drag_item = QGraphicsRectItem(QRectF(pos, pos))
        self._drag_item.setPen(BOX_PEN)
        self._scene.addItem(self._drag_item)

    def mouseMoveEvent(self, event):
        if self._drag_item is not None:
            rect = QRectF(self._drag_start, self.mapToScene(event.pos())).normalized()
            self._drag_item.setRect(rect)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_item is None:
            super().mouseReleaseEvent(event)
            return
        rect = self._drag_item.rect().intersected(self._scene.sceneRect())
        self._scene.removeItem(self._drag_item)
        self._drag_item = None
        self._drag_start = None
        if rect.width() < 4 or rect.height() < 4:
            return  # 太小的拖曳直接丟棄，畫面上不會留下任何東西
        item = BoxItem(rect)
        self._scene.addItem(item)
        self.on_box_drawn(item)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("element-splitter")
        self.resize(1200, 800)

        self.engine = SamEngine()
        self.image_path = None
        self.boxes = []  # list[BoxItem]，目前這個元素累積的框
        self.last_mask = None
        self.last_bbox = None

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top = QHBoxLayout()
        open_btn = QPushButton("開啟圖片")
        open_btn.clicked.connect(self.open_image)
        top.addWidget(open_btn)
        top.addStretch(1)
        root_layout.addLayout(top)

        body = QHBoxLayout()
        root_layout.addLayout(body, stretch=1)

        self.view = ImageView(self._on_box_drawn)
        body.addWidget(self.view, stretch=1)
        self.view.scene().selectionChanged.connect(self._on_selection_changed)

        side = QVBoxLayout()
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(280)
        body.addWidget(side_widget)

        side.addWidget(QLabel("目前元素的框："))
        self.box_list = QListWidget()
        self.box_list.itemSelectionChanged.connect(self._on_list_selection_changed)
        side.addWidget(self.box_list)

        del_btn = QPushButton("刪除選取的框")
        del_btn.clicked.connect(self.delete_selected_box)
        side.addWidget(del_btn)

        self.edit_group = QGroupBox("框座標微調（像素）")
        self.edit_group.setEnabled(False)
        form = QFormLayout(self.edit_group)
        self.spin_x0 = self._make_spin()
        self.spin_y0 = self._make_spin()
        self.spin_x1 = self._make_spin()
        self.spin_y1 = self._make_spin()
        form.addRow("x0", self.spin_x0)
        form.addRow("y0", self.spin_y0)
        form.addRow("x1", self.spin_x1)
        form.addRow("y1", self.spin_y1)
        side.addWidget(self.edit_group)

        run_btn = QPushButton("執行 SAM")
        run_btn.clicked.connect(self.run_sam)
        side.addWidget(run_btn)

        side.addWidget(QLabel("預覽："))
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(240, 240)
        self.preview_label.setStyleSheet("background:#555;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        side.addWidget(self.preview_label)

        export_btn = QPushButton("另存 PNG")
        export_btn.clicked.connect(self.export_png)
        side.addWidget(export_btn)

        next_btn = QPushButton("下一個元素（清空框）")
        next_btn.clicked.connect(self.next_element)
        side.addWidget(next_btn)

        side.addStretch(1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("請先開啟一張圖片")

    def _make_spin(self):
        spin = QDoubleSpinBox()
        spin.setDecimals(0)
        spin.setRange(0, 100000)
        spin.valueChanged.connect(self._on_spin_changed)
        return spin

    # ── 圖片載入 ────────────────────────────────────────────────────────────
    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇圖片", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        self.status.showMessage("載入模型與圖片中…（第一次會比較久）")
        QApplication.processEvents()
        try:
            self.engine.load_image(path)
        except Exception as e:  # noqa: BLE001 — 直接把錯誤原因顯示給使用者
            QMessageBox.critical(self, "載入失敗", str(e))
            self.status.showMessage("載入失敗")
            return

        self.image_path = path
        pil_img = Image.open(path).convert("RGB")
        self.view.set_image(pil_img)

        self.boxes.clear()
        self.box_list.clear()
        self._clear_preview()
        self.last_mask, self.last_bbox = None, None
        w, h = self.engine.source_size
        self.status.showMessage(f"已載入 {Path(path).name}（{w}x{h}）")

    # ── 畫框 / 選取 / 微調 ──────────────────────────────────────────────────
    def _on_box_drawn(self, item: BoxItem):
        self.boxes.append(item)
        list_item = QListWidgetItem(self._box_label(item))
        list_item.setData(Qt.UserRole, item)
        self.box_list.addItem(list_item)

    def _box_label(self, item: BoxItem) -> str:
        idx = self.boxes.index(item) + 1
        x0, y0, x1, y1 = (round(v) for v in item.to_xyxy())
        return f"box {idx}: ({x0}, {y0}, {x1}, {y1})"

    def _on_selection_changed(self):
        selected = [it for it in self.boxes if it.isSelected()]
        self.box_list.blockSignals(True)
        for i in range(self.box_list.count()):
            list_item = self.box_list.item(i)
            list_item.setSelected(list_item.data(Qt.UserRole) in selected)
        self.box_list.blockSignals(False)
        self._sync_spinboxes(selected[0] if len(selected) == 1 else None)

    def _on_list_selection_changed(self):
        selected_items = {li.data(Qt.UserRole) for li in self.box_list.selectedItems()}
        for box in self.boxes:
            box.setSelected(box in selected_items)

    def _sync_spinboxes(self, item):
        for spin in (self.spin_x0, self.spin_y0, self.spin_x1, self.spin_y1):
            spin.blockSignals(True)
        if item is None:
            self.edit_group.setEnabled(False)
        else:
            self.edit_group.setEnabled(True)
            x0, y0, x1, y1 = item.to_xyxy()
            self.spin_x0.setValue(x0)
            self.spin_y0.setValue(y0)
            self.spin_x1.setValue(x1)
            self.spin_y1.setValue(y1)
        for spin in (self.spin_x0, self.spin_y0, self.spin_x1, self.spin_y1):
            spin.blockSignals(False)

    def _on_spin_changed(self, _value):
        selected = [it for it in self.boxes if it.isSelected()]
        if len(selected) != 1:
            return
        item = selected[0]
        x0, y0, x1, y1 = self.spin_x0.value(), self.spin_y0.value(), self.spin_x1.value(), self.spin_y1.value()
        if x1 <= x0 or y1 <= y0:
            return  # 微調中途數值暫時不合法（例如還沒打完），先不套用
        item.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        idx = self.boxes.index(item)
        self.box_list.item(idx).setText(self._box_label(item))

    def delete_selected_box(self):
        selected = [it for it in self.boxes if it.isSelected()]
        if not selected:
            return
        for item in selected:
            self.boxes.remove(item)
            self.view.scene().removeItem(item)
        self.box_list.clear()
        for item in self.boxes:
            list_item = QListWidgetItem(self._box_label(item))
            list_item.setData(Qt.UserRole, item)
            self.box_list.addItem(list_item)
        self._sync_spinboxes(None)

    # ── SAM 推論 ────────────────────────────────────────────────────────────
    def run_sam(self):
        if self.image_path is None:
            QMessageBox.information(self, "提示", "請先開啟圖片")
            return
        if not self.boxes:
            QMessageBox.information(self, "提示", "請先畫至少一個框")
            return

        self.status.showMessage("執行 SAM 中…")
        QApplication.processEvents()
        boxes_xyxy = [b.to_xyxy() for b in self.boxes]
        try:
            mask, bbox = self.engine.segment_union(boxes_xyxy)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "SAM 執行失敗", str(e))
            self.status.showMessage("SAM 執行失敗")
            return

        if not mask.any():
            self.status.showMessage("沒切到東西（遮罩是空的），試試看調整框的範圍")
            self._clear_preview()
            self.last_mask, self.last_bbox = None, None
            return

        self.last_mask, self.last_bbox = mask, bbox
        cutout = self.engine.cutout(mask, bbox)
        self._show_preview(cutout)
        x0, y0, x1, y1 = (int(v) for v in bbox)
        coverage = mask[y0:y1, x0:x1].mean()
        self.status.showMessage(f"完成，覆蓋率 {coverage * 100:.1f}%（{len(self.boxes)} 個框聯集）")

    def _show_preview(self, cutout_img: Image.Image):
        pw, ph = self.preview_label.width(), self.preview_label.height()
        img = cutout_img.copy()
        img.thumbnail((pw, ph))
        bg = checkerboard(img.width, img.height).convert("RGBA")
        composed = Image.alpha_composite(bg, img)
        qimg = ImageQt(composed)
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

    def _clear_preview(self):
        self.preview_label.clear()

    # ── 匯出 / 下一個元素 ───────────────────────────────────────────────────
    def export_png(self):
        if self.last_mask is None:
            QMessageBox.information(self, "提示", "請先執行 SAM 且遮罩不是空的")
            return
        path, _ = QFileDialog.getSaveFileName(self, "另存 PNG", "", "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        cutout = self.engine.cutout(self.last_mask, self.last_bbox)
        cutout.save(path)
        self.status.showMessage(f"已存檔：{path}")

    def next_element(self):
        for item in self.boxes:
            self.view.scene().removeItem(item)
        self.boxes.clear()
        self.box_list.clear()
        self._sync_spinboxes(None)
        self._clear_preview()
        self.last_mask, self.last_bbox = None, None
        self.status.showMessage("已清空框，畫下一個元素")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
