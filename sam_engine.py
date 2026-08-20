"""sam_engine — wraps MobileSAM: load the model, compute the embedding once, union
multiple box prompts into one element's mask.

set_image() (the expensive step) is called once per image; the caller (app.py) only
needs to call load_image() again when switching images — cutting several elements out
of the same image reuses the same embedding.
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
                f"Model file not found: {CHECKPOINT}. Run: python doctor.py --fix"
            )
        from mobile_sam import SamPredictor, sam_model_registry

        sam = sam_model_registry["vit_t"](checkpoint=str(CHECKPOINT))
        sam.to(device="cpu")
        sam.eval()
        self._predictor = SamPredictor(sam)

    def load_image(self, path: str):
        """Switch images: read the file and compute the embedding once. No-op if the
        path matches the currently loaded image."""
        if path == self._image_path:
            return
        self._ensure_model()
        image = Image.open(path).convert("RGB")
        self._source = np.array(image)  # HWC RGB uint8 — exports read RGB from this
        self._predictor.set_image(self._source)
        self._image_path = path

    @property
    def source_rgb(self):
        """Full, uncropped source image as HWC RGB uint8 — background repair needs the
        context outside the hole, not just the cropped region."""
        return self._source

    @property
    def source_size(self):
        """(width, height) — used by the GUI for scale/coordinate conversion."""
        h, w = self._source.shape[:2]
        return w, h

    def segment_union(self, boxes_xyxy):
        """boxes_xyxy: list of (x0, y0, x1, y1) in original-image pixels, all boxes for
        the same element.

        Returns (mask, bbox):
          mask — bool ndarray the same size as the source image, boxes' masks unioned
          bbox — bounding box of all input boxes (x0, y0, x1, y1), used to crop on export
        """
        if not boxes_xyxy:
            raise ValueError("At least one box is required")

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
        """Fill the drawn boxes themselves (plain rectangles, no SAM) into a mask the
        same size as the source image.

        This is for "remove the element and repair the background", not "cut a
        transparent PNG": the latter wants SAM's precise edge, the former would rather
        over-cover a bit of background (LaMa can fill that in) than under-cover the
        element itself (SAM often misses a sliver of low-contrast or translucent
        material, and that leftover sliver would show through the repaired patch).
        That's why this deliberately doesn't reuse segment_union()'s mask.
        """
        h, w = self._source.shape[:2]
        mask = np.zeros((h, w), dtype=bool)
        for x0, y0, x1, y1 in boxes_xyxy:
            xi0, yi0 = max(0, int(round(x0))), max(0, int(round(y0)))
            xi1, yi1 = min(w, int(round(x1))), min(h, int(round(y1)))
            mask[yi0:yi1, xi0:xi1] = True
        return mask

    def cutout(self, mask: np.ndarray, bbox) -> Image.Image:
        """Crop to bbox; RGB comes from the untouched source pixels (never zeroed),
        alpha comes from the mask."""
        x0, y0, x1, y1 = (int(v) for v in bbox)
        rgb = self._source[y0:y1, x0:x1]
        alpha = mask[y0:y1, x0:x1].astype(np.uint8) * 255
        rgba = np.dstack([rgb, alpha])
        return Image.fromarray(rgba, mode="RGBA")
