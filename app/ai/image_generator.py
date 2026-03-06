"""AI Image Generator — Creates scene images via Stable Diffusion or ComfyUI."""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ImageGeneratorBase(ABC):
    """Interface for image generation engines."""

    @abstractmethod
    async def generate(self, prompt: str, output_path: Path, negative_prompt: str = "") -> Path:
        """Generate an image from *prompt* and save it. Returns the path."""
        ...


# ── Stable Diffusion WebUI (Automatic1111) ────────────────────────────────────


class StableDiffusionGenerator(ImageGeneratorBase):
    """Calls the Automatic1111 / Forge / SD.Next REST API."""

    def __init__(self, api_url: str | None = None):
        self.api_url = (api_url or settings.sd_api_url).rstrip("/")

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        negative_prompt: str = "text, watermark, blurry, low quality",
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": 30,
            "cfg_scale": 7.5,
            "width": 1280,
            "height": 720,
            "sampler_name": "DPM++ 2M Karras",
            "batch_size": 1,
        }

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.api_url}/sdapi/v1/txt2img",
                json=payload,
            )
            resp.raise_for_status()

        data = resp.json()
        img_b64: str = data["images"][0]
        img_bytes = base64.b64decode(img_b64)
        output_path.write_bytes(img_bytes)
        logger.info("SD image → %s (%d bytes)", output_path.name, len(img_bytes))
        return output_path


# ── ComfyUI ────────────────────────────────────────────────────────────────────


class ComfyUIGenerator(ImageGeneratorBase):
    """Calls ComfyUI's API (simplified — enqueues a prompt and retrieves output)."""

    def __init__(self, api_url: str | None = None):
        self.api_url = (api_url or settings.comfyui_api_url).rstrip("/")

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        negative_prompt: str = "text, watermark, blurry, low quality",
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Minimal ComfyUI workflow payload (users should customise)
        workflow = {
            "prompt": {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 42,
                        "steps": 30,
                        "cfg": 7.5,
                        "sampler_name": "dpmpp_2m",
                        "scheduler": "karras",
                        "denoise": 1.0,
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["5", 0],
                    },
                },
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1280, "height": 720, "batch_size": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["4", 1]}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "scene", "images": ["8", 0]}},
            }
        }

        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(f"{self.api_url}/prompt", json=workflow)
            resp.raise_for_status()
            prompt_id = resp.json()["prompt_id"]

            # Poll for completion
            import asyncio
            for _ in range(120):  # max 10 min
                await asyncio.sleep(5)
                hist = await client.get(f"{self.api_url}/history/{prompt_id}")
                if hist.status_code == 200 and hist.json():
                    break

            # Download the output image
            history = hist.json().get(prompt_id, {})
            outputs = history.get("outputs", {})
            for node_output in outputs.values():
                images = node_output.get("images", [])
                if images:
                    img_info = images[0]
                    img_resp = await client.get(
                        f"{self.api_url}/view",
                        params={"filename": img_info["filename"], "subfolder": img_info.get("subfolder", ""), "type": img_info.get("type", "output")},
                    )
                    img_resp.raise_for_status()
                    output_path.write_bytes(img_resp.content)
                    logger.info("ComfyUI image → %s", output_path.name)
                    return output_path

        raise RuntimeError("ComfyUI did not produce an image.")


# ── Placeholder (for testing without SD) ───────────────────────────────────────


class PlaceholderImageGenerator(ImageGeneratorBase):
    """Generates simple gradient images with text overlay using Pillow.

    No external service needed — perfect for pipeline testing.
    """

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        negative_prompt: str = "",
    ) -> Path:
        from PIL import Image, ImageDraw, ImageFont
        import hashlib

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate a color from the prompt hash for variety
        h = int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16)
        r1, g1, b1 = (h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF
        r2, g2, b2 = 255 - r1, 255 - g1, 255 - b1

        # Create gradient background
        img = Image.new("RGB", (1280, 720))
        for y in range(720):
            ratio = y / 720
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            for x in range(1280):
                img.putpixel((x, y), (r, g, b))

        # Overlay prompt text
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except OSError:
            font = ImageFont.load_default()

        # Wrap text
        words = prompt[:120].split()
        lines = []
        line = ""
        for w in words:
            if len(line + " " + w) > 40:
                lines.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            lines.append(line)

        y_pos = 300
        for line_text in lines:
            draw.text((100, y_pos), line_text, fill=(255, 255, 255), font=font)
            y_pos += 35

        # Label
        draw.text((20, 20), "[PLACEHOLDER]", fill=(255, 255, 0), font=font)

        img.save(output_path, "PNG")
        logger.info("Placeholder image → %s", output_path.name)
        return output_path


# ── Replicate API (cloud GPU — no local hardware required) ─────────────────────


class ReplicateImageGenerator(ImageGeneratorBase):
    """Calls the Replicate API for cloud GPU image generation.

    Free tier exists; paid tier is ~$0.0023/image for SDXL.
    Set IMAGE_ENGINE=replicate and REPLICATE_API_KEY in your .env.
    Model IDs:  stability-ai/sdxl, black-forest-labs/flux-schnell, etc.
    """

    API_URL = "https://api.replicate.com/v1"

    def __init__(self, api_key: str | None = None, model_id: str | None = None):
        self.api_key = api_key or settings.replicate_api_key
        self.model_id = model_id or settings.replicate_model_id

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        negative_prompt: str = "text, watermark, blurry, low quality, nsfw",
    ) -> Path:
        if not self.api_key:
            raise RuntimeError(
                "REPLICATE_API_KEY is not set. Add it to your .env or Railway variables."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=300) as client:
            # Start prediction
            resp = await client.post(
                f"{self.API_URL}/models/{self.model_id}/predictions",
                headers=headers,
                json={
                    "input": {
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "width": 1280,
                        "height": 720,
                        "num_outputs": 1,
                    }
                },
            )
            resp.raise_for_status()
            prediction = resp.json()
            prediction_url = prediction["urls"]["get"]

            # Poll until done (max 5 minutes)
            import asyncio
            for _ in range(60):
                await asyncio.sleep(5)
                poll = await client.get(prediction_url, headers=headers)
                poll.raise_for_status()
                data = poll.json()
                if data["status"] == "succeeded":
                    image_url = data["output"][0]
                    break
                if data["status"] == "failed":
                    raise RuntimeError(f"Replicate prediction failed: {data.get('error')}")
            else:
                raise TimeoutError("Replicate image generation timed out after 5 minutes")

            # Download the image
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            output_path.write_bytes(img_resp.content)

        logger.info("Replicate image → %s (%d bytes)", output_path.name, len(img_resp.content))
        return output_path


# ── Factory ────────────────────────────────────────────────────────────────────────


def get_image_generator() -> ImageGeneratorBase:
    """Return the configured image generation engine."""
    engine = settings.image_engine.lower()
    if engine == "comfyui":
        return ComfyUIGenerator()
    if engine == "replicate":
        return ReplicateImageGenerator()
    if engine == "placeholder":
        return PlaceholderImageGenerator()
    return StableDiffusionGenerator()
