"""inpaint_engine — wraps LaMa (simple-lama-inpainting): repair the masked region of
the full source image.

Independent of sam_engine.SamEngine — separate model, no shared state. SimpleLama is
lazily instantiated (only on the first repair() call); that first call also downloads
the TorchScript checkpoint (~196MB, cached in the torch hub directory, not managed by
this project's models/).

MAX_SIDE cap: LaMa's Fourier Convolutions are a global operation, so memory use
explodes with resolution. Measured on a MacBook Air M2 16GB: a 1672x941 image pushed
peak memory footprint to about 19.5GB (beyond physical RAM — severe slowdowns or the
process getting killed outright); capping the long side to 1024 brought that down to
about 8.1GB, which leaves a safe margin on a 16GB machine. So LaMa always runs at a
capped resolution, and only the repaired pixels within the mask get pasted back onto
the full-resolution source — the rest of the image keeps its original pixels instead of
going blurry from the resize round-trip.
"""
import numpy as np
from PIL import Image

MAX_SIDE = 1024  # see module docstring — a memory-safety bound, not a quality choice


class InpaintEngine:
    def __init__(self, max_side: int = MAX_SIDE):
        self._lama = None
        self.max_side = max_side

    def _ensure_model(self):
        if self._lama is None:
            from simple_lama_inpainting import SimpleLama

            self._lama = SimpleLama()

    def repair(self, source_rgb: np.ndarray, mask: np.ndarray) -> Image.Image:
        """source_rgb: full, uncropped source image as HWC RGB uint8 (LaMa needs to see
        the context outside the hole to fill it plausibly).
        mask: bool ndarray the same size as the source, True marks the region to repair.
        Returns the full repaired RGB image at the source's original size; only pixels
        inside the mask come from the repair — everything else keeps its original
        resolution.
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
        # LaMa also pads the image to a multiple of 8 internally, so the output is a
        # few pixels larger than what went in — crop the extra off.
        small_result = small_result.crop((0, 0, small_source.width, small_source.height))

        if scale < 1.0:
            upscaled = small_result.resize((w, h), Image.LANCZOS)
        else:
            upscaled = small_result

        # Only pixels inside the mask come from the (possibly upscaled) repair; outside
        # the mask, paste back the untouched source so the whole image doesn't go soft
        # from the downscale/upscale round-trip.
        composited = source_img.copy()
        composited.paste(upscaled, (0, 0), mask_img)
        return composited
