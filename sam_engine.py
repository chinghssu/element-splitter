"""sam_engine — 包裝 MobileSAM：載入模型、算一次 embedding、多框聯集出一個元素的遮罩。

同一張圖片只呼叫一次 predictor.set_image()（貴的一步），呼叫端（app.py）只要在換圖片時
重新 load_image，同一張圖切多個元素不用重算。
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
CHECKPOINT = HERE / "models" / "mobile_sam.pt"


class SamEngine:
    def __init__(self):
        self._predictor = None
        self._image_path = None

    def _ensure_model(self):
        if self._predictor is not None:
            return
        if not CHECKPOINT.exists():
            raise RuntimeError(
                f"找不到模型檔 {CHECKPOINT}。請先執行：python doctor.py --fix"
            )
        from mobile_sam import SamPredictor, sam_model_registry

        sam = sam_model_registry["vit_t"](checkpoint=str(CHECKPOINT))
        sam.to(device="cpu")
        sam.eval()
        self._predictor = SamPredictor(sam)

    def load_image(self, path: str):
        """換圖片：讀檔、算一次 embedding。與目前已載入的圖片相同則跳過。"""
        if path == self._image_path:
            return
        self._ensure_model()
        image = Image.open(path).convert("RGB")
        self._source = np.array(image)  # HWC RGB uint8，匯出時 RGB 取自這份原圖
        self._predictor.set_image(self._source)
        self._image_path = path

    @property
    def source_rgb(self):
        """完整原圖 HWC RGB uint8（未裁切）——修補背景要用到洞外的上下文，不能只給裁切區域。"""
        return self._source

    @property
    def source_size(self):
        """(width, height) — 給 GUI 換算縮放座標用。"""
        h, w = self._source.shape[:2]
        return w, h

    def segment_union(self, boxes_xyxy):
        """boxes_xyxy: list of (x0, y0, x1, y1) 原圖像素座標，同一個元素的多個框。

        回傳 (mask, bbox)：
          mask — 跟原圖同尺寸的 bool ndarray，多框遮罩已做聯集
          bbox — 所有輸入框的聯集外接框 (x0, y0, x1, y1)，匯出時用這個裁切
        """
        if not boxes_xyxy:
            raise ValueError("至少要有一個框")

        h, w = self._source.shape[:2]
        union_mask = np.zeros((h, w), dtype=bool)
        for box in boxes_xyxy:
            masks, scores, _ = self._predictor.predict(
                box=np.array(box), multimask_output=False
            )
            union_mask |= masks[0]

        xs0 = [b[0] for b in boxes_xyxy]
        ys0 = [b[1] for b in boxes_xyxy]
        xs1 = [b[2] for b in boxes_xyxy]
        ys1 = [b[3] for b in boxes_xyxy]
        bbox = (min(xs0), min(ys0), max(xs1), max(ys1))
        return union_mask, bbox

    def box_union_mask(self, boxes_xyxy) -> np.ndarray:
        """把畫的框本身（矩形，不經過 SAM）填成遮罩，回傳跟原圖同尺寸的 bool ndarray。

        用途是「移除素材補背景」，不是「切透明 PNG」：後者要 SAM 的精細邊緣，前者寧可
        多挖一點背景（LaMa 補得動）也不能漏挖到素材本身（SAM 對低對比/半透明部位常常
        漏切一角，殘留的那塊會直接穿幫在補好的背景上）。所以這裡刻意不用 segment_union
        算出來的遮罩。
        """
        h, w = self._source.shape[:2]
        mask = np.zeros((h, w), dtype=bool)
        for x0, y0, x1, y1 in boxes_xyxy:
            xi0, yi0 = max(0, int(round(x0))), max(0, int(round(y0)))
            xi1, yi1 = min(w, int(round(x1))), min(h, int(round(y1)))
            mask[yi0:yi1, xi0:xi1] = True
        return mask

    def cutout(self, mask: np.ndarray, bbox) -> Image.Image:
        """裁切到 bbox，RGB 取自原圖未修改的像素（不歸零），alpha 用遮罩。"""
        x0, y0, x1, y1 = (int(v) for v in bbox)
        rgb = self._source[y0:y1, x0:x1]
        alpha = mask[y0:y1, x0:x1].astype(np.uint8) * 255
        rgba = np.dstack([rgb, alpha])
        return Image.fromarray(rgba, mode="RGBA")
