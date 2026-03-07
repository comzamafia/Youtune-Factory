"""AI Script Generator — Splits novel text into video scenes using an LLM."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


# ── Data Models ────────────────────────────────────────────────────────────────


class SceneData(BaseModel):
    """One scene produced by the LLM."""

    scene_number: int
    text: str
    image_prompt: str
    mood: str = "neutral"
    part: int = 1  # video part number (for multi-part splitting)


# ── Abstract Base ──────────────────────────────────────────────────────────────


class ScriptGeneratorBase(ABC):
    """Interface for any LLM-based script generator."""

    @abstractmethod
    async def generate_scenes(self, novel_text: str, title: str = "") -> list[SceneData]:
        ...


# ── OpenAI-Compatible Implementation ──────────────────────────────────────────


SYSTEM_PROMPT = """\
You are a JSON-only video scriptwriter. You NEVER output markdown, tables, or explanations.
Your task is to split a novel excerpt into short video scenes.

Rules:
- Each scene should last 5-8 seconds when narrated.
- Keep the original language of the text.
- For each scene provide: scene text, a detailed image prompt (English, for AI image generation), and a mood keyword.
- Return ONLY a JSON array. No other text before or after.
- Keys must be exactly: scene_number, text, image_prompt, mood
- Do NOT wrap in markdown code fences or backticks.
- Do NOT include any explanation, thinking, comments, or markdown.
- Your entire response must start with [ and end with ]
"""

USER_PROMPT_TEMPLATE = """\
Novel Title: {title}

Split the following novel text into video scenes:

---
{text}
---

Return a JSON array. Example element:
{{"scene_number": 1, "text": "...", "image_prompt": "...", "mood": "mysterious"}}
"""


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from potentially noisy LLM output.

    Handles:
    - Qwen3.5 <think>...</think> tags
    - Markdown ```json ... ``` fences
    - Leading/trailing text around the JSON
    - Truncated JSON (auto-close incomplete arrays)
    """
    cleaned = raw.strip()

    # 1. Remove <think>...</think> blocks (Qwen3.5)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    # 2. Remove markdown code fences
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

    # 3. Try direct parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 4. Regex fallback: find first [ ... ] block
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # 5. Try to fix truncated JSON by finding complete objects within the array
    if "[" in cleaned:
        start_idx = cleaned.index("[")
        fragment = cleaned[start_idx:]
        # Find all '}' positions and try closing the array after each (last to first)
        brace_positions = [i for i, c in enumerate(fragment) if c == '}']
        for pos in reversed(brace_positions):
            candidate = fragment[:pos + 1] + ']'
            try:
                result = json.loads(candidate)
                if isinstance(result, list) and len(result) > 0:
                    logger.warning(
                        "Repaired truncated JSON: kept %d complete objects out of truncated response",
                        len(result),
                    )
                    return result
            except json.JSONDecodeError:
                continue

    logger.error("Failed to extract JSON. Raw content (first 500 chars): %s", cleaned[:500])
    raise ValueError(f"Could not extract JSON array from LLM response: {cleaned[:200]}...")


class OpenAIScriptGenerator(ScriptGeneratorBase):
    """Calls any OpenAI-compatible chat endpoint (works with Ollama, vLLM, etc.)."""

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_base = (api_base or settings.llm_api_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model

    async def _preload_model(self) -> None:
        """Pre-load the Ollama model into VRAM before inference.

        Calls Ollama's native /api/generate with an empty prompt, which loads
        the model without generating any output. This guarantees the model is
        hot in VRAM before the actual inference request, eliminating ReadTimeout
        caused by model-loading delays.

        Only runs for localhost Ollama; no-op for cloud APIs.
        """
        import time

        ollama_base = self.api_base.replace("/v1", "").rstrip("/")
        logger.info("Pre-loading model '%s' into VRAM via Ollama…", self.model)
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=600, write=10, pool=10)
            ) as client:
                resp = await client.post(
                    f"{ollama_base}/api/generate",
                    json={"model": self.model, "prompt": "", "keep_alive": "1h", "stream": False},
                )
                resp.raise_for_status()
            logger.info("Model '%s' ready in %.1fs", self.model, time.monotonic() - start)
        except Exception as e:
            logger.warning(
                "Model pre-load failed after %.1fs (%s: %s) — will proceed anyway",
                time.monotonic() - start, type(e).__name__, e,
            )

    async def generate_scenes(self, novel_text: str, title: str = "") -> list[SceneData]:
        """Send novel text to the LLM and parse the scene list.

        Long novels are automatically chunked to fit the LLM context window.
        Includes automatic retry (up to 3 attempts) per chunk.
        """
        # For local Ollama: pre-load the model into VRAM before inference.
        # This separates model-loading time from inference time, ensuring the
        # actual generation request never times out waiting for model loading.
        if "localhost:11434" in self.api_base:
            await self._preload_model()

        chunks = _chunk_novel_text(novel_text, max_chars=settings.llm_chunk_max_chars)

        if len(chunks) > 1:
            logger.info(
                "Novel text split into %d chunks (max %d chars each)",
                len(chunks), settings.llm_chunk_max_chars,
            )

        all_scenes: list[SceneData] = []
        global_scene_num = 0

        for chunk_idx, chunk in enumerate(chunks, start=1):
            # Rate-limit delay between chunks (Groq free tier = 6000 TPM)
            # Skip long delay for local Ollama (no rate limits)
            if chunk_idx > 1:
                import asyncio
                is_local = "localhost" in self.api_base or "127.0.0.1" in self.api_base
                delay = 2 if is_local else 15
                logger.info("Waiting %ds between chunks%s…", delay, "" if is_local else " (rate limit)")
                await asyncio.sleep(delay)

            chunk_scenes = await self._generate_scenes_for_chunk(
                chunk, title, chunk_idx, len(chunks),
            )
            # Re-number scenes globally
            for sc in chunk_scenes:
                global_scene_num += 1
                sc.scene_number = global_scene_num
            all_scenes.extend(chunk_scenes)

        if len(all_scenes) > settings.max_total_scenes:
            logger.warning(
                "Generated %d scenes exceeds max_total_scenes=%d, truncating.",
                len(all_scenes), settings.max_total_scenes,
            )
            all_scenes = all_scenes[: settings.max_total_scenes]

        logger.info("Total scenes generated: %d (from %d chunks)", len(all_scenes), len(chunks))
        return all_scenes

    async def _generate_scenes_for_chunk(
        self,
        chunk_text: str,
        title: str,
        chunk_number: int,
        total_chunks: int,
    ) -> list[SceneData]:
        """Generate scenes for a single chunk of novel text."""
        import asyncio

        user_msg = USER_PROMPT_TEMPLATE.format(title=title, text=chunk_text)
        if total_chunks > 1:
            user_msg += f"\n(This is part {chunk_number} of {total_chunks} — continue numbering from 1 for this chunk)"

        # Qwen3.5: append /no_think to disable thinking mode (saves tokens)
        is_qwen = "qwen" in self.model.lower()
        if is_qwen:
            user_msg += "\n/no_think"

        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.4,
        }

        # Ollama-specific: use num_predict instead of max_tokens
        # (max_tokens via OpenAI compat layer caps thinking+output combined,
        #  causing empty responses when thinking uses all tokens)
        # num_predict: 8192 — 13 scenes × ~200 tokens/scene JSON ≈ 2600 tokens;
        #   use 8192 to give ample room for larger novels without truncation.
        # num_ctx: 16384 — Thai text is dense (~1-2 chars/token); a 6000-char
        #   chunk can consume 3000-6000 tokens, easily overflowing num_ctx=4096
        #   which causes Ollama to silently clip input → bad/truncated JSON.
        if "localhost:11434" in self.api_base:
            payload["options"] = {
                "num_predict": 8192,
                "num_ctx": 16384,
            }
            # keep_alive for ALL local models (not just Qwen) so the model
            # stays hot between chunks and doesn't cause timeout on reload.
            payload["keep_alive"] = "1h"
        else:
            # Cloud APIs (Groq, OpenAI, etc.)
            payload["max_tokens"] = 2048

        max_retries = 5
        last_error: Exception | None = None

        logger.info("Calling LLM: %s model=%s", self.api_base, self.model)

        # Ollama may need extra time for model loading + inference on first run.
        # A 9-10B model at Q4 can take 60-120s to load + 60-120s to infer.
        read_timeout = 600 if "localhost" in self.api_base else 120

        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=10, read=read_timeout, write=30, pool=10)
                ) as client:
                    resp = await client.post(
                        f"{self.api_base}/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()

                data = resp.json()
                raw_content: str = data["choices"][0]["message"]["content"]
                logger.info("LLM response length: %d chars (attempt %d/%d)", len(raw_content), attempt, max_retries)

                # Empty response => retry
                if not raw_content or len(raw_content.strip()) < 10:
                    logger.warning("Empty or too-short LLM response on attempt %d, retrying...", attempt)
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)  # exponential backoff
                        continue
                    raise ValueError("LLM returned empty response after all retries")

                logger.debug("LLM raw response: %s", raw_content[:500])

                # Parse with robust extraction
                scenes_raw = _extract_json_array(raw_content)

                if not scenes_raw:
                    logger.warning("Parsed 0 scenes on attempt %d, retrying...", attempt)
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)
                        continue
                    raise ValueError("LLM returned no scenes after all retries")

                scenes: list[SceneData] = []
                for i, s in enumerate(scenes_raw, start=1):
                    # Tolerate alternate key names (Qwen3.5 sometimes varies)
                    scene_num = s.get("scene_number") or s.get("scene") or i
                    scene_text = s.get("text") or s.get("narration") or s.get("description", "")
                    img_prompt = s.get("image_prompt") or s.get("image_desc") or s.get("visual", "")
                    scenes.append(
                        SceneData(
                            scene_number=int(scene_num),
                            text=scene_text,
                            image_prompt=img_prompt,
                            mood=s.get("mood", "neutral"),
                        )
                    )

                logger.info(
                    "Generated %d scenes for '%s' (chunk %d/%d)",
                    len(scenes), title, chunk_number, total_chunks,
                )
                return scenes

            except httpx.ConnectError as e:
                # Connection refused / unreachable — fail fast, don't burn retries
                raise RuntimeError(
                    f"Cannot connect to LLM at {self.api_base}: {e}. "
                    f"Check LLM_API_BASE_URL env var."
                ) from e

            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_error = e
                # 429 rate limit — use longer backoff
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    wait = min(60, 15 * attempt)  # 15, 30, 45, 60, 60
                    logger.warning("Rate limited (429) on attempt %d, waiting %ds…", attempt, wait)
                elif isinstance(e, httpx.TimeoutException):
                    wait = 3 * attempt
                    logger.warning(
                        "LLM request timed out on attempt %d/%d (%s). "
                        "Ollama may still be loading the model. Waiting %ds…",
                        attempt, max_retries, type(e).__name__, wait,
                    )
                else:
                    wait = 3 * attempt
                    logger.warning("HTTP error on attempt %d: %s", attempt, e)
                if attempt < max_retries:
                    await asyncio.sleep(wait)
                    continue

            except httpx.HTTPError as e:
                last_error = e
                logger.warning("HTTP transport error on attempt %d: %s", attempt, e)
                if attempt < max_retries:
                    await asyncio.sleep(3 * attempt)
                    continue

            except ValueError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning("Parse error on attempt %d: %s, retrying...", attempt, e)
                    await asyncio.sleep(2 * attempt)
                    continue

        err_type = type(last_error).__name__ if last_error is not None else "UnknownError"
        err_msg = str(last_error) if last_error is not None else "no error details captured"
        raise RuntimeError(
            f"Failed to generate scenes after {max_retries} attempts: "
            f"{err_type}: {err_msg}"
        )


# ── Factory ────────────────────────────────────────────────────────────────────


# ── Novel Chunking ─────────────────────────────────────────────────────────────


def _chunk_novel_text(text: str, max_chars: int = 3000) -> list[str]:
    """Split novel text into chunks that fit the LLM context window.

    Splits on paragraph boundaries (double newline) to keep semantic coherence.
    Falls back to single-newline splitting, then hard character split.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)

    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If a single paragraph is too long, split it further
        if len(para) > max_chars:
            # Flush current chunk first
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            # Split oversized paragraph by sentences or hard limit
            sub_parts = _split_long_paragraph(para, max_chars)
            chunks.extend(sub_parts)
            continue

        if len(current_chunk) + len(para) + 2 > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _split_long_paragraph(text: str, max_chars: int) -> list[str]:
    """Split an oversized paragraph by sentences, then by hard character limit."""
    # Try sentence-level split
    sentences = re.split(r"(?<=[.!?。！？\n])\s+", text)
    if len(sentences) > 1:
        parts: list[str] = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) + 1 > max_chars:
                if current:
                    parts.append(current.strip())
                current = sent
            else:
                current = current + " " + sent if current else sent
        if current:
            parts.append(current.strip())
        return parts

    # Hard character split as last resort
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def get_script_generator() -> ScriptGeneratorBase:
    """Return the configured script generator."""
    return OpenAIScriptGenerator()
