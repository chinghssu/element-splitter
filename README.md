# element-splitter

A small desktop tool for cutting elements out of a flat image (illustrations, product
photos, screenshots) into transparent PNGs using MobileSAM, and optionally repairing the
background where an element was removed using LaMa — similar to Canva's "move an
element, the hole gets filled in" effect.

Fully independent of any other project: standalone Python, standalone repo, no shared
code.

其他語言：[繁體中文](README.zh-TW.md)

## Install

```bash
pip install -r requirements.txt
python doctor.py --fix   # downloads the MobileSAM checkpoint (~40MB)
```

Run `doctor.py` without `--fix` any time to check what's missing.

The background-repair feature downloads an additional ~196MB LaMa checkpoint the first
time you use it (cached by `torch.hub`, not managed by this project's `models/`).

## Usage

```bash
python app.py
```

1. **Open Image** — pick a PNG/JPG.
2. Drag on the canvas to draw a box around the element you want to cut out. One element
   can have several boxes (e.g. the main body plus a thin protruding part, or a
   high-contrast sticker/label area) — **Run SAM** unions all of their masks.
   - Scroll to zoom in for pixel-precise placement; a selected box's coordinates can
     also be fine-tuned with the x0/y0/x1/y1 spinboxes in the side panel.
3. The side panel shows a live preview of the cut-out element (transparent PNG on a
   checkerboard backdrop). **Save Element PNG** writes it to disk.
4. **Repair Background (remove boxed area)** removes the boxed element from the source
   image using LaMa inpainting and shows the result on the main canvas. **Save
   Background PNG** writes that out once you're happy with it.
   - This uses the *drawn boxes* as the removal area, not SAM's precise mask — see
     "Known limitations" below for why.
5. **Next Element** clears the current boxes so you can cut another element out of the
   same image (the image's SAM embedding is computed once and reused).

## Known limitations

- Box prompts only — no click/point prompts.
- SAM sometimes excludes a part of the object that's very different in color/texture
  from the rest (a sticker, or something visible through translucent packaging) — you
  may need an extra box to bring it into the union. This is normal behavior for a
  box-prompted segmenter, not a bug in this tool.
- **Background repair intentionally uses the union of your drawn boxes, not SAM's fine
  mask, as the area to remove.** Early testing showed that feeding SAM's precise mask to
  LaMa left a visible sliver of the original object untouched exactly where SAM had
  excluded a low-contrast part — the object never fully disappeared. Over-covering with
  a rectangle is safe (LaMa can plausibly fill extra background); under-covering the
  element is not.
- **Memory**: LaMa's Fourier Convolutions are a global operation, and memory use grows
  sharply with image resolution. Measured on a MacBook Air M2 (16GB RAM): inpainting a
  1672x941 image directly pushed peak memory footprint to ~19.5GB — beyond the machine's
  physical RAM, causing severe slowdowns or the process being killed. To stay safe,
  `inpaint_engine.py` always runs LaMa on a copy capped at 1024px on the long side
  (measured peak: ~8.3GB) and only pastes the repaired pixels back into the removal
  area on the full-resolution image — everything else keeps its original pixels, so
  quality outside the repaired patch is unaffected.
- No on-disk embedding cache, no batch processing across multiple files — see
  `requirement.md`'s non-goals.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
