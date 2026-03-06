"""Tests for the script generator — validates prompt construction and JSON parsing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.script_generator import OpenAIScriptGenerator, SceneData


MOCK_LLM_RESPONSE = json.dumps([
    {
        "scene_number": 1,
        "text": "The night was silent and cold.",
        "image_prompt": "dark night landscape with fog, cinematic lighting",
        "mood": "mysterious",
    },
    {
        "scene_number": 2,
        "text": "A shadow moved through the trees.",
        "image_prompt": "dark forest with silhouette figure, horror atmosphere",
        "mood": "tense",
    },
    {
        "scene_number": 3,
        "text": "He reached the abandoned castle.",
        "image_prompt": "medieval castle ruins at night, dramatic moonlight",
        "mood": "dramatic",
    },
])


@pytest.mark.asyncio
async def test_generate_scenes_parses_json():
    """LLM response is correctly parsed into SceneData objects."""
    gen = OpenAIScriptGenerator(api_base="http://test", api_key="key", model="test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": MOCK_LLM_RESPONSE}}]
    }

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        scenes = await gen.generate_scenes("Once upon a time...", title="Test Story")

    assert len(scenes) == 3
    assert all(isinstance(s, SceneData) for s in scenes)
    assert scenes[0].text == "The night was silent and cold."
    assert scenes[1].mood == "tense"
    assert scenes[2].image_prompt == "medieval castle ruins at night, dramatic moonlight"


@pytest.mark.asyncio
async def test_handles_markdown_fenced_json():
    """LLM response wrapped in ```json ... ``` is still parsed correctly."""
    gen = OpenAIScriptGenerator(api_base="http://test", api_key="key", model="test")

    fenced = f"```json\n{MOCK_LLM_RESPONSE}\n```"
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": fenced}}]
    }

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        scenes = await gen.generate_scenes("text", title="Test")

    assert len(scenes) == 3
    assert scenes[0].scene_number == 1
