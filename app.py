#!/usr/bin/env python3
"""element-splitter — 畫框、跑 MobileSAM、把元素切成透明 PNG 的小 GUI。

    python app.py
"""
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from PIL import Image, ImageTk

from sam_engine import SamEngine

MAX_CANVAS_SIDE = 900  # 圖片顯示縮放上限（畫布可視範圍），座標一律換算回原圖像素
CHECKER = 12  # 預覽棋盤格底圖的格子邊長（像素）


def checkerboard(w, h, size=CHECKER):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            light = ((x // size) + (y // size)) % 2 == 0
            px[x, y] = (235, 235, 235) if light else (200, 200, 200)
    return img


class App:
    def __init__(self, root):
        self.root = root
        root.title("element-splitter")

        self.engine = SamEngine()
        self.image_path = None
        self.display_scale = 1.0
        self.tk_image = None  # 保留參照避免被回收
        self.preview_tk = None

        self.boxes = []  # list of (x0,y0,x1,y1) 原圖像素座標，目前這個元素累積的框
        self.drag_start = None
        self.drag_rect_id = None

        self.last_mask = None
        self.last_bbox = None

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        top = tk.Frame(self.root)
        top.pack(side=tk.TOP, fill=tk.X)
        tk.Button(top, text="開啟圖片", command=self.open_image).pack(side=tk.LEFT, padx=4, pady=4)
        self.status = tk.StringVar(value="請先開啟一張圖片")
        tk.Label(top, textvariable=self.status, anchor="w").pack(side=tk.LEFT, padx=8)

        body = tk.Frame(self.root)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(body, bg="#333", width=MAX_CANVAS_SIDE, height=MAX_CANVAS_SIDE)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        side = tk.Frame(body, width=260)
        side.pack(side=tk.RIGHT, fill=tk.Y)

        tk.Label(side, text="目前元素的框：").pack(anchor="w", padx=6, pady=(6, 0))
        self.box_list = tk.Listbox(side, height=6)
        self.box_list.pack(fill=tk.X, padx=6)
        tk.Button(side, text="刪除選取的框", command=self._delete_selected_box).pack(fill=tk.X, padx=6, pady=(2, 8))

        tk.Button(side, text="執行 SAM", command=self.run_sam).pack(fill=tk.X, padx=6, pady=(0, 8))

        tk.Label(side, text="預覽：").pack(anchor="w", padx=6)
        self.preview_canvas = tk.Canvas(side, bg="#555", width=240, height=240)
        self.preview_canvas.pack(padx=6, pady=(0, 8))

        tk.Button(side, text="另存 PNG", command=self.export_png).pack(fill=tk.X, padx=6, pady=(0, 4))
        tk.Button(side, text="下一個元素（清空框）", command=self.next_element).pack(fill=tk.X, padx=6)

    # ── 圖片載入與座標換算 ──────────────────────────────────────────────────────
    def open_image(self):
        path = filedialog.askopenfilename(
            title="選擇圖片", filetypes=[("Images", "*.png *.jpg *.jpeg")]
        )
        if not path:
            return
        self.status.set("載入模型與圖片中…（第一次會比較久）")
        self.root.update_idletasks()
        try:
            self.engine.load_image(path)
        except Exception as e:  # noqa: BLE001 — 直接把錯誤原因顯示給使用者
            messagebox.showerror("載入失敗", str(e))
            self.status.set("載入失敗")
            return

        self.image_path = path
        w, h = self.engine.source_size
        self.display_scale = min(1.0, MAX_CANVAS_SIDE / max(w, h))
        disp_w, disp_h = int(w * self.display_scale), int(h * self.display_scale)

        pil_img = Image.open(path).convert("RGB").resize((disp_w, disp_h))
        self.tk_image = ImageTk.PhotoImage(pil_img)
        self.canvas.config(width=disp_w, height=disp_h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image, tags="bg")

        self.boxes.clear()
        self.box_list.delete(0, tk.END)
        self._clear_preview()
        self.status.set(f"已載入 {Path(path).name}（{w}x{h}）")

    def _to_image_coords(self, cx, cy):
        return cx / self.display_scale, cy / self.display_scale

    def _to_canvas_coords(self, ix, iy):
        return ix * self.display_scale, iy * self.display_scale

    # ── 畫框互動 ────────────────────────────────────────────────────────────
    def _on_press(self, event):
        if self.image_path is None:
            return
        self.drag_start = (event.x, event.y)
        self.drag_rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00ff88", width=2
        )

    def _on_drag(self, event):
        if self.drag_rect_id is None:
            return
        x0, y0 = self.drag_start
        self.canvas.coords(self.drag_rect_id, x0, y0, event.x, event.y)

    def _on_release(self, event):
        if self.drag_rect_id is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        self.drag_start = None
        self.drag_rect_id = None

        if (x1 - x0) < 4 or (y1 - y0) < 4:
            self.status.set("框太小，已忽略（至少要拖出幾個像素）")
            self._redraw_boxes()
            return

        ix0, iy0 = self._to_image_coords(x0, y0)
        ix1, iy1 = self._to_image_coords(x1, y1)
        w, h = self.engine.source_size
        ix0, iy0 = max(0, ix0), max(0, iy0)
        ix1, iy1 = min(w, ix1), min(h, iy1)

        box = (ix0, iy0, ix1, iy1)
        self.boxes.append(box)
        self.box_list.insert(tk.END, f"box {len(self.boxes)}: {tuple(round(v) for v in box)}")
        self._redraw_boxes()

    def _redraw_boxes(self):
        self.canvas.delete("box")
        for box in self.boxes:
            cx0, cy0 = self._to_canvas_coords(box[0], box[1])
            cx1, cy1 = self._to_canvas_coords(box[2], box[3])
            self.canvas.create_rectangle(cx0, cy0, cx1, cy1, outline="#00ff88", width=2, tags="box")

    def _delete_selected_box(self):
        sel = self.box_list.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.boxes[idx]
        self.box_list.delete(idx)
        for i in range(self.box_list.size()):
            self.box_list.delete(i)
        for i, box in enumerate(self.boxes):
            self.box_list.insert(tk.END, f"box {i + 1}: {tuple(round(v) for v in box)}")
        self._redraw_boxes()

    # ── SAM 推論 ────────────────────────────────────────────────────────────
    def run_sam(self):
        if self.image_path is None:
            messagebox.showinfo("提示", "請先開啟圖片")
            return
        if not self.boxes:
            messagebox.showinfo("提示", "請先畫至少一個框")
            return

        self.status.set("執行 SAM 中…")
        self.root.update_idletasks()
        try:
            mask, bbox = self.engine.segment_union(self.boxes)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("SAM 執行失敗", str(e))
            self.status.set("SAM 執行失敗")
            return

        if not mask.any():
            self.status.set("沒切到東西（遮罩是空的），試試看調整框的範圍")
            self._clear_preview()
            self.last_mask, self.last_bbox = None, None
            return

        self.last_mask, self.last_bbox = mask, bbox
        cutout = self.engine.cutout(mask, bbox)
        self._show_preview(cutout)
        coverage = mask[int(bbox[1]):int(bbox[3]), int(bbox[0]):int(bbox[2])].mean()
        self.status.set(f"完成，覆蓋率 {coverage * 100:.1f}%（{len(self.boxes)} 個框聯集）")

    def _show_preview(self, cutout_img: Image.Image):
        pw, ph = self.preview_canvas.winfo_width() or 240, self.preview_canvas.winfo_height() or 240
        img = cutout_img.copy()
        img.thumbnail((pw, ph))
        bg = checkerboard(img.width, img.height)
        composed = Image.alpha_composite(bg.convert("RGBA"), img)
        self.preview_tk = ImageTk.PhotoImage(composed)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(pw // 2, ph // 2, image=self.preview_tk)

    def _clear_preview(self):
        self.preview_canvas.delete("all")
        self.preview_tk = None

    # ── 匯出 / 下一個元素 ───────────────────────────────────────────────────
    def export_png(self):
        if self.last_mask is None:
            messagebox.showinfo("提示", "請先執行 SAM 且遮罩不是空的")
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not path:
            return
        cutout = self.engine.cutout(self.last_mask, self.last_bbox)
        cutout.save(path)
        self.status.set(f"已存檔：{path}")

    def next_element(self):
        self.boxes.clear()
        self.box_list.delete(0, tk.END)
        self.canvas.delete("box")
        self._clear_preview()
        self.last_mask, self.last_bbox = None, None
        self.status.set("已清空框，畫下一個元素")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
