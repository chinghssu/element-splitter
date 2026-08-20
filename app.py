#!/usr/bin/env python3
"""element-splitter — draw boxes, run MobileSAM, cut elements into transparent PNGs (PySide6).

    python app.py

Boxes are independent QGraphicsRectItem objects. The scene's coordinate system is
unaffected by view zoom, so:
  - Drawing and deleting boxes are plain scene-item add/remove operations — no leftover
    outlines when a box is cancelled or deleted (the old Tkinter version had this bug:
    the temporary drag rectangle didn't share a tag with committed boxes, so clearing
    the canvas only cleared tagged items and the temporary one stayed forever).
  - Mouse-wheel zoom lets you line up edges precisely, and the coordinate spinboxes in
    the side panel let you nudge a selected box pixel by pixel — more precise than a
    freehand drag alone.
"""
import sys
from pathlib import Path

# PySide6 must be imported before `from PIL.ImageQt import ImageQt`: PIL.ImageQt
# auto-detects which Qt binding to use — whichever is already in sys.modules wins,
# otherwise it defaults to trying PyQt6 first. If the environment also has PyQt6
# installed (a separate, otherwise-unrelated binding) and the import order is wrong,
# Pillow loads PyQt6's QtCore first; when PySide6.QtCore is imported afterwards,
# macOS's dyld conflates the two identically-named QtCore.framework bundles and
# crashes outright (ImportError: Symbol not found).
from PIL import Image
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

from PIL.ImageQt import ImageQt  # after PySide6 — see note above
from inpaint_engine import InpaintEngine
from sam_engine import SamEngine

CHECKER = 12  # checkerboard tile size (px) for the transparent-preview backdrop
BOX_PEN = QPen(QColor("#00ff88"), 2)
BOX_PEN.setCosmetic(True)  # keep line width constant across zoom levels
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
    """One drawn box. rect() is in original-image pixel coordinates (scene space is
    unaffected by view zoom)."""

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
        option.state &= ~option.state.__class__.State_Selected  # skip Qt's default dashed outline
        super().paint(painter, option, widget)


class ImageView(QGraphicsView):
    """Image canvas: mouse-wheel zoom, drag-to-draw a box on empty space, or click an
    existing box to let Qt handle selection."""

    def __init__(self, on_box_drawn):
        super().__init__()
        self.on_box_drawn = on_box_drawn
        self.setRenderHint(QPainter.Antialiasing, False)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._bg_item = None
        self._original_pixmap = None
        self._drag_start = None
        self._drag_item = None
        self.setDragMode(QGraphicsView.NoDrag)

    def set_image(self, pil_image: Image.Image):
        self._scene.clear()
        self._drag_item = None
        qimg = ImageQt(pil_image.convert("RGB"))
        pix = QPixmap.fromImage(qimg)
        self._original_pixmap = pix
        self._bg_item = self._scene.addPixmap(pix)
        self._bg_item.setZValue(0)
        self._scene.setSceneRect(0, 0, pix.width(), pix.height())
        self.resetTransform()

    def show_overlay(self, pil_image: Image.Image):
        """Temporarily swap the displayed background for a full-canvas result (e.g. a
        background-repair preview) without touching the scene's box items or rect."""
        if self._bg_item is None:
            return
        qimg = ImageQt(pil_image.convert("RGB"))
        self._bg_item.setPixmap(QPixmap.fromImage(qimg))

    def restore_original(self):
        """Switch the background back to the originally loaded image."""
        if self._bg_item is not None and self._original_pixmap is not None:
            self._bg_item.setPixmap(self._original_pixmap)

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
            super().mousePressEvent(event)  # let Qt handle select/deselect
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
            return  # discard tiny drags — nothing is left behind on the canvas
        item = BoxItem(rect)
        self._scene.addItem(item)
        self.on_box_drawn(item)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("element-splitter")
        self.resize(1200, 800)

        self.engine = SamEngine()
        self.inpaint = InpaintEngine()
        self.image_path = None
        self.boxes = []  # list[BoxItem] — boxes accumulated for the current element
        self.last_mask = None
        self.last_bbox = None
        self.last_repaired = None  # PIL.Image result from repair_background(), pending export

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top = QHBoxLayout()
        open_btn = QPushButton("Open Image")
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

        side.addWidget(QLabel("Boxes for this element:"))
        self.box_list = QListWidget()
        self.box_list.itemSelectionChanged.connect(self._on_list_selection_changed)
        side.addWidget(self.box_list)

        del_btn = QPushButton("Delete Selected Box")
        del_btn.clicked.connect(self.delete_selected_box)
        side.addWidget(del_btn)

        self.edit_group = QGroupBox("Fine-tune box (pixels)")
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

        run_btn = QPushButton("Run SAM")
        run_btn.clicked.connect(self.run_sam)
        side.addWidget(run_btn)

        side.addWidget(QLabel("Element preview:"))
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(240, 240)
        self.preview_label.setStyleSheet("background:#555;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        side.addWidget(self.preview_label)

        export_btn = QPushButton("Save Element PNG")
        export_btn.clicked.connect(self.export_png)
        side.addWidget(export_btn)

        repair_btn = QPushButton("Repair Background (remove boxed area)")
        repair_btn.clicked.connect(self.repair_background)
        side.addWidget(repair_btn)

        export_repair_btn = QPushButton("Save Background PNG")
        export_repair_btn.clicked.connect(self.export_repaired_png)
        side.addWidget(export_repair_btn)

        next_btn = QPushButton("Next Element (clear boxes)")
        next_btn.clicked.connect(self.next_element)
        side.addWidget(next_btn)

        side.addStretch(1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Open an image to get started")

    def _make_spin(self):
        spin = QDoubleSpinBox()
        spin.setDecimals(0)
        spin.setRange(0, 100000)
        spin.valueChanged.connect(self._on_spin_changed)
        return spin

    # ── Image loading ───────────────────────────────────────────────────────
    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        self.status.showMessage("Loading model and image... (first run is slower)")
        QApplication.processEvents()
        try:
            self.engine.load_image(path)
        except Exception as e:  # noqa: BLE001 — surface the real error to the user
            QMessageBox.critical(self, "Load Failed", str(e))
            self.status.showMessage("Load failed")
            return

        self.image_path = path
        pil_img = Image.open(path).convert("RGB")
        self.view.set_image(pil_img)

        self.boxes.clear()
        self.box_list.clear()
        self._clear_preview()
        self.last_mask, self.last_bbox = None, None
        self.last_repaired = None
        w, h = self.engine.source_size
        self.status.showMessage(f"Loaded {Path(path).name} ({w}x{h})")

    # ── Drawing / selection / fine-tuning ──────────────────────────────────
    def _on_box_drawn(self, item: BoxItem):
        self.view.restore_original()  # drawing a new box means we're editing again
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
            return  # mid-edit values can be momentarily invalid (e.g. still typing) — skip
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

    # ── SAM inference ───────────────────────────────────────────────────────
    def run_sam(self):
        if self.image_path is None:
            QMessageBox.information(self, "Notice", "Open an image first")
            return
        if not self.boxes:
            QMessageBox.information(self, "Notice", "Draw at least one box first")
            return

        self.view.restore_original()
        self.status.showMessage("Running SAM...")
        QApplication.processEvents()
        boxes_xyxy = [b.to_xyxy() for b in self.boxes]
        try:
            mask, bbox = self.engine.segment_union(boxes_xyxy)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "SAM Failed", str(e))
            self.status.showMessage("SAM failed")
            return

        if not mask.any():
            self.status.showMessage("Nothing was segmented (empty mask) — try adjusting the boxes")
            self._clear_preview()
            self.last_mask, self.last_bbox = None, None
            return

        self.last_mask, self.last_bbox = mask, bbox
        cutout = self.engine.cutout(mask, bbox)
        self._show_preview(cutout)
        x0, y0, x1, y1 = (int(v) for v in bbox)
        coverage = mask[y0:y1, x0:x1].mean()
        self.status.showMessage(f"Done. Coverage {coverage * 100:.1f}% ({len(self.boxes)} box(es) union)")

    def _show_preview(self, cutout_img: Image.Image):
        """Small side-panel preview of the extracted element (transparent PNG on a
        checkerboard backdrop). Kept separate from the main-canvas repair preview."""
        pw, ph = self.preview_label.width(), self.preview_label.height()
        img = cutout_img.copy()
        img.thumbnail((pw, ph))
        bg = checkerboard(img.width, img.height).convert("RGBA")
        composed = Image.alpha_composite(bg, img)
        qimg = ImageQt(composed)
        self.preview_label.setPixmap(QPixmap.fromImage(qimg))

    def _clear_preview(self):
        self.preview_label.clear()

    # ── Export / next element ───────────────────────────────────────────────
    def export_png(self):
        if self.last_mask is None:
            QMessageBox.information(self, "Notice", "Run SAM first and make sure the mask isn't empty")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Element PNG", "", "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        cutout = self.engine.cutout(self.last_mask, self.last_bbox)
        cutout.save(path)
        self.status.showMessage(f"Saved: {path}")

    def repair_background(self):
        if not self.boxes:
            QMessageBox.information(self, "Notice", "Draw at least one box around the element to remove")
            return

        # Deliberately use the drawn boxes themselves (rectangle union), not SAM's
        # fine-grained mask: SAM often misses a sliver of low-contrast or translucent
        # material, and that leftover sliver would show up unrepaired. Over-covering
        # with the box is safe — LaMa can fill extra background — but under-covering
        # the element itself is not.
        removal_mask = self.engine.box_union_mask([b.to_xyxy() for b in self.boxes])

        self.status.showMessage("Repairing background... (first run also downloads the model)")
        QApplication.processEvents()
        try:
            repaired = self.inpaint.repair(self.engine.source_rgb, removal_mask)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Repair Failed", str(e))
            self.status.showMessage("Repair failed")
            return

        self.last_repaired = repaired
        self.view.show_overlay(repaired)  # full-size result belongs on the main canvas, not the small side preview
        self.status.showMessage('Repair done — showing the result on the canvas. Click "Save Background PNG" to keep it.')

    def export_repaired_png(self):
        if self.last_repaired is None:
            QMessageBox.information(self, "Notice", 'Click "Repair Background" first')
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Background PNG", "", "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        self.last_repaired.save(path)
        self.status.showMessage(f"Saved: {path}")

    def next_element(self):
        for item in self.boxes:
            self.view.scene().removeItem(item)
        self.boxes.clear()
        self.box_list.clear()
        self._sync_spinboxes(None)
        self._clear_preview()
        self.view.restore_original()
        self.last_mask, self.last_bbox = None, None
        self.last_repaired = None
        self.status.showMessage("Boxes cleared — draw the next element")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
