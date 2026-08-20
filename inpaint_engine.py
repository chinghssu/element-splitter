"""inpaint_engine — 包裝 LaMa（simple-lama-inpainting）：對完整原圖的遮罩區域補洞。

跟 sam_engine.SamEngine 是兩個獨立的模型，互不依賴、也不共用快取。SimpleLama 是惰性
載入（第一次呼叫 repair() 才建立），第一次會自動下載 TorchScript checkpoint
（約 196MB，快取在 torch hub 目錄，不歸這個專案的 models/ 管）。
"""
import numpy as np
from PIL import Image


class InpaintEngine:
    def __init__(self):
        self._lama = None

    def _ensure_model(self):
        if self._lama is None:
            from simple_lama_inpainting import SimpleLama

            self._lama = SimpleLama()

    def repair(self, source_rgb: np.ndarray, mask: np.ndarray) -> Image.Image:
        """source_rgb: 完整原圖 HWC RGB uint8（未裁切——LaMa 要看得到洞外的紋理才補得像）。
        mask: 跟原圖同尺寸的 bool ndarray，True 代表要補的區域。回傳補好洞的完整 RGB 圖。
        """
        self._ensure_model()
        h, w = source_rgb.shape[:2]
        image = Image.fromarray(source_rgb, mode="RGB")
        mask_img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
        result = self._lama(image, mask_img)
        # LaMa 內部把圖片 pad 到 8 的倍數再推論，輸出會比原圖多幾像素；裁回原尺寸，
        # 不然這張背景圖之後沒辦法跟素材原本的座標對齊。
        return result.crop((0, 0, w, h))
