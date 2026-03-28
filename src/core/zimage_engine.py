"""Z-Image-Turbo img2img-based upscale: LANCZOS resize + AI refinement (diffusers)."""

from __future__ import annotations

from pathlib import Path

from core.zimage_beautify_prompts import BEAUTIFY_NEGATIVE, build_beautify_positive


def compute_output_size(ow: int, oh: int, scale: int, max_side: int) -> tuple[int, int]:
    """Integer sizes multiple of 8; cap longest edge to max_side (VRAM)."""
    tw, th = ow * scale, oh * scale
    longest = max(tw, th)
    if longest > max_side and longest > 0:
        r = max_side / longest
        tw = int(tw * r)
        th = int(th * r)
    tw = max(8, (tw // 8) * 8)
    th = max(8, (th // 8) * 8)
    return tw, th


class ZImageUpscaleEngine:
    """Loads pipeline from a local Hugging Face snapshot directory."""

    def __init__(self, snapshot_dir: Path):
        self.snapshot_dir = Path(snapshot_dir)
        self._pipe = None

    def unload(self) -> None:
        self._pipe = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def run(
        self,
        image_path: str,
        scale: int,
        max_side: int,
        strength: float,
        num_inference_steps: int,
        cfg: float,
        log,
        portrait_detected: bool = False,
        freckle_heavy: bool = False,
        beautify: bool = False,
        beautify_analysis: str | None = None,
    ):
        import torch
        from diffusers import ZImageImg2ImgPipeline
        from PIL import Image, ImageOps

        if torch.cuda.is_available():
            device = "cuda"
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        else:
            device = "cpu"
            dtype = torch.float32
            log("Using CPU for Z-Image (no CUDA). This will be slow and needs substantial RAM.")

        if self._pipe is None:
            log("Loading Z-Image Img2Img pipeline (first time may take a while)…")
            self._pipe = ZImageImg2ImgPipeline.from_pretrained(
                str(self.snapshot_dir),
                torch_dtype=dtype,
                local_files_only=True,
            )
            self._pipe.to(device)
            if hasattr(self._pipe, "enable_vae_slicing"):
                try:
                    self._pipe.enable_vae_slicing()
                except Exception:
                    pass
            log("Pipeline ready.")

        img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
        ow, oh = img.size
        tw, th = compute_output_size(ow, oh, scale, max_side)
        want_w, want_h = ow * scale, oh * scale
        if tw != (max(8, (want_w // 8) * 8)) or th != (max(8, (want_h // 8) * 8)):
            log(
                f"Note: requested {want_w}×{want_h}px; using {tw}×{th}px "
                f"(max edge {max_side}px) to reduce VRAM use."
            )

        init = img.resize((tw, th), Image.Resampling.LANCZOS)
        effective_strength = float(strength)
        apply_beautify = bool(portrait_detected and beautify)

        _faithful_upscale = (
            "very high detail photorealistic upscale, faithful to the source photograph, minimal change, "
            "preserve original colors skin tone and texture, sharp fine detail, clean edges, "
            "subtle denoise only, no beautification, no added redness or color cast, no new spots or freckles"
        )

        if apply_beautify:
            cfg_value = max(0.0, min(12.0, float(cfg)))
            run_prompt = build_beautify_positive(
                freckle_heavy=freckle_heavy,
                analysis_notes=beautify_analysis,
            )
        else:
            cfg_value = 0.0
            run_prompt = _faithful_upscale
        log(
            f"Refining {tw}×{th}px with Z-Image-Turbo "
            f"(strength={effective_strength:.2f}, steps={num_inference_steps}, cfg={cfg_value:.1f})…"
        )
        try:
            if apply_beautify:
                try:
                    result = self._pipe(
                        run_prompt,
                        negative_prompt=BEAUTIFY_NEGATIVE,
                        image=init,
                        strength=effective_strength,
                        num_inference_steps=int(num_inference_steps),
                        guidance_scale=cfg_value,
                    ).images[0]
                except TypeError:
                    log("Beautify: negative_prompt not supported by this pipeline; using positive prompt only.")
                    result = self._pipe(
                        run_prompt,
                        image=init,
                        strength=effective_strength,
                        num_inference_steps=int(num_inference_steps),
                        guidance_scale=cfg_value,
                    ).images[0]
            else:
                result = self._pipe(
                    run_prompt,
                    image=init,
                    strength=effective_strength,
                    num_inference_steps=int(num_inference_steps),
                    guidance_scale=cfg_value,
                ).images[0]
        except Exception as e:
            from core.ai_inference_resources import USER_MSG_CUDA_OOM, ZIMAGE_VRAM_BASELINE_LOG
            from core.gpu_errors import is_torch_cuda_oom

            if is_torch_cuda_oom(e):
                raise RuntimeError(f"{USER_MSG_CUDA_OOM} ({ZIMAGE_VRAM_BASELINE_LOG})") from e
            raise
        return result

