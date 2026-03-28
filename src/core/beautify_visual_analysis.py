"""
Local BLIP image-captioning for Beautify: full-face skin/makeup passes plus per-region facial detail.

Uses ``Salesforce/blip-image-captioning-base`` (transformers stack; first run downloads weights
into the Hugging Face cache, same as Z-Image). Runs on CPU to leave GPU memory for Z-Image.

Face subregions use heuristic splits inside the OpenCV face box (no landmark model).
"""

from __future__ import annotations

import gc
import re
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

# Small BLIP; conditional captioning continues from the text prefix.
BEAUTIFY_ANALYSIS_MODEL_ID = "Salesforce/blip-image-captioning-base"

_blip_processor = None
_blip_model = None

# Skip tiny crops (very small faces / degenerate boxes).
_MIN_REGION_PX = 40

# (internal_key, human_label, x0_frac, y0_frac, w_frac, h_frac) relative to **face bbox**
_FACE_REGION_LAYOUT: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("forehead", "forehead and brow", 0.08, 0.0, 0.84, 0.30),
    ("eyes_brows", "eyes and brows", 0.05, 0.20, 0.90, 0.28),
    ("nose", "nose and midface", 0.30, 0.34, 0.40, 0.32),
    ("left_cheek", "left cheek", 0.05, 0.40, 0.38, 0.28),
    ("right_cheek", "right cheek", 0.57, 0.40, 0.38, 0.28),
    ("mouth_lips", "mouth and lips", 0.18, 0.60, 0.64, 0.22),
    ("chin_jaw", "chin and jaw", 0.12, 0.78, 0.76, 0.22),
)


def unload_beautify_analyzer() -> None:
    """Release BLIP weights before loading Z-Image to reduce peak RAM/VRAM."""
    global _blip_processor, _blip_model
    _blip_processor = None
    _blip_model = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _sanitize_analysis_notes(s: str, *, max_len: int = 280) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0]
    return s


def _conditional_caption(
    processor,
    model,
    crop,
    text_prefix: str,
    *,
    max_gen_length: int = 100,
) -> str:
    """Run BLIP conditional generation; return completion with prefix stripped."""
    import torch

    inputs = processor(images=crop, text=text_prefix, return_tensors="pt")
    inputs = {k: v.to("cpu") for k, v in inputs.items()}
    with torch.no_grad():
        out_ids = model.generate(
            **inputs,
            max_length=max_gen_length,
            num_beams=4,
            do_sample=False,
        )
    decoded = processor.decode(out_ids[0], skip_special_tokens=True)
    raw = decoded.strip()
    plow = text_prefix.lower()
    if raw.lower().startswith(plow):
        raw = raw[len(text_prefix) :].strip(" ,.;:")
    else:
        raw = raw.strip()
    return raw


# Full-face prefixes (wide crop).
_SKIN_PREFIX = "This portrait shows skin and complexion issues such as"
_MAKEUP_PREFIX = (
    "For this face, balanced editorial makeup and grooming appropriate to the source photo could include"
)


def _region_analysis_prefix(human_label: str) -> str:
    """Prefix steers BLIP toward detailed observation of one facial zone."""
    return (
        f"Detailed facial analysis of the {human_label} in this photograph: "
        f"visible skin texture, tone, and features include"
    )


def _face_to_abs_box(
    face: tuple[int, int, int, int],
    img_w: int,
    img_h: int,
    x0f: float,
    y0f: float,
    wf: float,
    hf: float,
) -> tuple[int, int, int, int]:
    x, y, w, h = face
    xa = x + int(x0f * w)
    ya = y + int(y0f * h)
    wa = max(1, int(wf * w))
    ha = max(1, int(hf * h))
    xa = max(0, min(xa, img_w - 1))
    ya = max(0, min(ya, img_h - 1))
    wa = min(wa, img_w - xa)
    ha = min(ha, img_h - ya)
    return xa, ya, wa, ha


def _iter_region_crops(
    pil_rgb: Image.Image,
    face_bbox: tuple[int, int, int, int],
) -> list[tuple[str, str, Image.Image]]:
    """Return (key, human_label, crop) for each valid subregion of the face box."""
    W, H = pil_rgb.size
    out: list[tuple[str, str, Image.Image]] = []
    for key, human, x0f, y0f, wf, hf in _FACE_REGION_LAYOUT:
        box = _face_to_abs_box(face_bbox, W, H, x0f, y0f, wf, hf)
        xa, ya, wa, ha = box
        if wa < _MIN_REGION_PX or ha < _MIN_REGION_PX:
            continue
        crop = pil_rgb.crop((xa, ya, xa + wa, ya + ha))
        if crop.width < _MIN_REGION_PX or crop.height < _MIN_REGION_PX:
            continue
        out.append((key, human, crop))
    return out


def _load_blip(log: Callable[[str], None]):
    global _blip_processor, _blip_model
    if _blip_processor is not None and _blip_model is not None:
        return _blip_processor, _blip_model
    try:
        from transformers import BlipForConditionalGeneration, BlipProcessor
    except ImportError as e:
        log(f"Beautify analysis skipped (transformers not available: {e}).")
        return None, None

    log("Loading BLIP for Beautify analysis (first run may download ~1 GB from Hugging Face)…")
    try:
        _blip_processor = BlipProcessor.from_pretrained(BEAUTIFY_ANALYSIS_MODEL_ID)
        _blip_model = BlipForConditionalGeneration.from_pretrained(BEAUTIFY_ANALYSIS_MODEL_ID)
        _blip_model.eval()
        _blip_model = _blip_model.to("cpu")
    except Exception as e:
        log(f"Beautify analysis could not load BLIP: {e}")
        _blip_processor = None
        _blip_model = None
        return None, None

    log("BLIP ready for Beautify analysis.")
    return _blip_processor, _blip_model


def _crop_face_rgb(pil_rgb: Image.Image, face: tuple[int, int, int, int], *, margin: float = 0.18) -> Image.Image:
    w_img, h_img = pil_rgb.size
    x, y, w, h = face
    mx = int(w * margin)
    my = int(h * margin)
    x0 = max(0, x - mx)
    y0 = max(0, y - my)
    x1 = min(w_img, x + w + mx)
    y1 = min(h_img, y + h + my)
    return pil_rgb.crop((x0, y0, x1, y1))


def analyze_beautify_imperfections(
    image_path: str | Path,
    face_bbox: tuple[int, int, int, int],
    log: Callable[[str], None],
) -> str:
    """
    Run BLIP on the full face (skin + makeup) and on heuristic subregions (forehead, eyes, nose,
    cheeks, mouth, chin) for detailed notes, merged for the diffusion prompt.

    Unloads BLIP weights when done so Z-Image can load with less memory pressure.
    """
    path = Path(image_path)
    if not path.is_file():
        return ""

    processor, model = _load_blip(log)
    if processor is None or model is None:
        unload_beautify_analyzer()
        return ""

    try:
        pil = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        crop_full = _crop_face_rgb(pil, face_bbox)
        if crop_full.width < 32 or crop_full.height < 32:
            return ""

        parts: list[str] = []

        skin_raw = _conditional_caption(processor, model, crop_full, _SKIN_PREFIX, max_gen_length=100)
        skin_notes = _sanitize_analysis_notes(skin_raw, max_len=280)
        if skin_notes:
            parts.append(f"Overall skin/complexion: {skin_notes}")

        makeup_raw = _conditional_caption(processor, model, crop_full, _MAKEUP_PREFIX, max_gen_length=100)
        makeup_notes = _sanitize_analysis_notes(makeup_raw, max_len=280)
        if makeup_notes:
            parts.append(f"Overall makeup/grooming: {makeup_notes}")

        regional: list[str] = []
        for _key, human, rcrop in _iter_region_crops(pil, face_bbox):
            prefix = _region_analysis_prefix(human)
            raw = _conditional_caption(processor, model, rcrop, prefix, max_gen_length=110)
            sn = _sanitize_analysis_notes(raw, max_len=200)
            if sn:
                regional.append(f"{human.capitalize()}: {sn}")

        if regional:
            parts.append("Regional detail — " + " | ".join(regional))

        merged = " ".join(parts)
        merged = _sanitize_analysis_notes(merged, max_len=2200)
        if merged:
            log(
                f"Beautify analysis (BLIP full face + {len(regional)} regions): {merged[:280]}"
                f"{'…' if len(merged) > 280 else ''}"
            )
        return merged
    except Exception as e:
        log(f"Beautify analysis failed (continuing without notes): {e}")
        return ""
    finally:
        unload_beautify_analyzer()
