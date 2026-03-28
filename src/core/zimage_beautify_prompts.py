"""
Beautify mode prompts for Z-Image img2img (AI Image Upscaler).

**Models:** Beautify uses the same **Z-Image-Turbo** img2img checkpoint as the rest of this panel.
**OpenCV** (bundled) finds the face region; optional **BLIP** (``Salesforce/blip-image-captioning-base``,
via transformers — first run downloads ~1 GB into the HF cache) runs full-face and per-region
captions (heuristic forehead, eyes, nose, cheeks, mouth, chin) plus skin/makeup summaries.
If BLIP is unavailable, Beautify still runs with the built-in retouch text and freckle heuristics only.

**Reference aesthetic:** Freepik Pikaso space *“High-end skin retouch & makeup”* (editorial,
photography-grade skin work — natural texture, not plastic). We do not call Freepik APIs; prompts
encode a similar intent. Campaign link:
https://www.freepik.com/pikaso/spaces/a160e7da-e42e-41a9-bcfb-c0ae347984e0

Design goals:
- Short, coherent positives; gender branches inferred from the photo.
- Negative prompt targets blush, plastic skin, doll face (when the pipeline supports it).

See also: CapCut on TikTok beauty filters (soft vs glam).
"""

from __future__ import annotations

# Canonical Pikaso space (utm params optional for sharing).
PIKASO_HIGH_END_SKIN_SPACE_URL = (
    "https://www.freepik.com/pikaso/spaces/a160e7da-e42e-41a9-bcfb-c0ae347984e0"
)

# Concise — diffusion models follow this better than paragraph stacks of “no X no Y”.
BEAUTIFY_NEGATIVE = (
    "blush, rouge, blusher, pink cheeks, red cheeks, rosy cheeks, flushed cheeks, heavy makeup, "
    "plastic skin, waxy skin, doll face, distorted face, over-smoothed skin, garish lipstick, "
    "anime face, fake tan streak, cheap beauty filter, heavy Instagram filter"
)


def build_beautify_positive(
    *,
    freckle_heavy: bool,
    analysis_notes: str | None = None,
) -> str:
    """
    :param freckle_heavy: optional heuristic for denser freckling.
    :param analysis_notes: optional local BLIP text (skin + makeup guidance, sanitized) merged into the prompt.
    """
    # High-end editorial skin retouch (Pikaso “High-end skin retouch & makeup” intent): pro photo polish, not glam overload.
    core = (
        "High-end editorial skin retouch, photorealistic, same identity and expression as the photograph. "
        "Professional beauty-retouch: even skin tone, gentle blemish and texture softening, "
        "preserved natural pores and skin detail, not plastic or waxy. "
        "Soft neutral lighting, color-accurate, no added pink or red on cheeks or nose. "
        "Women: refined natural feminine polish, minimal visible makeup. "
        "Men: clean groomed masculine look, sharp but natural, matte skin, no cosmetic cheek color. "
        "Infer feminine vs masculine presentation from the image. Subtle photography-grade enhancement only."
    )
    if freckle_heavy:
        core += " Slightly soften dense freckles toward even tone without erasing character."

    base = f"Pikaso-style high-end skin retouch: {core}"
    notes = (analysis_notes or "").strip()
    if notes:
        return (
            f"{base} Follow local photo analysis for subtle corrections and editorial makeup where it fits "
            f"(natural, not heavy): {notes}"
        )
    return base
