"""inpaint_engine — 包裝 LaMa（simple-lama-inpainting）：對完整原圖的遮罩區域補洞。

跟 sam_engine.SamEngine 是兩個獨立的模型，互不依賴、也不共用快取。SimpleLama 是惰性
載入（第一次呼叫 repair() 才建立），第一次會自動下載 TorchScript checkpoint
（約 196MB，快取在 torch hub 目錄，不歸這個專案的 models/ 管）。

MAX_SIDE 限制：LaMa 的 Fourier Convolution 是全域運算，記憶體隨解析度暴增。實測在
MacBook Air M2 16GB 上，一張 1672x941 的圖 peak memory footprint 衝到約 19.5GB
（超過實體記憶體，會嚴重拖慢甚至被系統砍掉行程）；縮到長邊 1024 之後降到約 8.1GB，
在 16GB 機器上才留得住安全餘裕。所以固定在較低解析度跑 LaMa，推論完只把補好的內容
貼回遮罩範圍，畫面其他地方維持原始解析度的像素，不整張跟著模糊。
"""
import numpy as np
from PIL import Image

MAX_SIDE = 1024  # 見上方說明：這是記憶體安全邊界，不是畫質考量


class InpaintEngine:
    def __init__(self, max_side: int = MAX_SIDE):
        self._lama = None
        self.max_side = max_side

    def _ensure_model(self):
        if self._lama is None:
            from simple_lama_inpainting import SimpleLama

            self._lama = SimpleLama()

    def repair(self, source_rgb: np.ndarray, mask: np.ndarray) -> Image.Image:
        """source_rgb: 完整原圖 HWC RGB uint8（未裁切——LaMa 要看得到洞外的紋理才補得像）。
        mask: 跟原圖同尺寸的 bool ndarray，True 代表要補的區域。回傳補好洞、跟原圖同尺寸的
        完整 RGB 圖；只有遮罩範圍內的像素會被換成修補結果，其餘維持原始解析度像素。
        """
        self._ensure_model()
        h, w = source_rgb.shape[:2]
        source_img = Image.fromarray(source_rgb, mode="RGB")
        mask_img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")

        scale = min(1.0, self.max_side / max(w, h))
        if scale < 1.0:
            small_size = (max(1, round(w * scale)), max(1, round(h * scale)))
            small_source = source_img.resize(small_size, Image.LANCZOS)
            small_mask = mask_img.resize(small_size, Image.NEAREST)
        else:
            small_source, small_mask = source_img, mask_img

        small_result = self._lama(small_source, small_mask)
        # LaMa 內部另外把圖片 pad 到 8 的倍數再推論，輸出會比丟進去的尺寸多幾像素，
        # 裁掉多的部分。
        small_result = small_result.crop((0, 0, small_source.width, small_source.height))

        if scale < 1.0:
            upscaled = small_result.resize((w, h), Image.LANCZOS)
        else:
            upscaled = small_result

        # 只把遮罩範圍內的像素換成修補結果，範圍外貼回原圖的原始像素，避免整張圖
        # 都被縮放-放大這一趟拖成模糊。
        composited = source_img.copy()
        composited.paste(upscaled, (0, 0), mask_img)
        return composited
