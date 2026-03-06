"""Tests for long-content handling: novel chunking, multi-part support, and resource management."""

from __future__ import annotations

import re
import uuid

import pytest

from app.ai.script_generator import (
    SceneData,
    _chunk_novel_text,
    _split_long_paragraph,
)
from app.core.models import Novel, Scene, Video


# ── Novel Text Chunking ───────────────────────────────────────────────────────


class TestChunkNovelText:
    """Tests for _chunk_novel_text function."""

    def test_short_text_single_chunk(self):
        """Text shorter than max_chars returns a single chunk."""
        text = "This is a short novel."
        chunks = _chunk_novel_text(text, max_chars=3000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text(self):
        """Empty text returns single empty-ish chunk."""
        chunks = _chunk_novel_text("", max_chars=3000)
        assert len(chunks) == 1

    def test_splits_on_paragraph_boundary(self):
        """Long text is split at paragraph boundaries (double newline)."""
        para1 = "A" * 1500
        para2 = "B" * 1500
        text = f"{para1}\n\n{para2}"
        chunks = _chunk_novel_text(text, max_chars=2000)
        assert len(chunks) == 2
        assert chunks[0].strip() == para1
        assert chunks[1].strip() == para2

    def test_keeps_paragraphs_together_when_possible(self):
        """Small paragraphs that fit together stay in one chunk."""
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        chunks = _chunk_novel_text(text, max_chars=3000)
        assert len(chunks) == 1

    def test_many_paragraphs(self):
        """Multiple paragraphs produce correct number of chunks."""
        paragraphs = [f"Paragraph {i}. " + "x" * 200 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = _chunk_novel_text(text, max_chars=500)
        # Each chunk should be at most 500 chars
        for chunk in chunks:
            assert len(chunk) <= 550  # slight tolerance for paragraph joining

    def test_oversized_single_paragraph_split(self):
        """A single paragraph larger than max_chars is force-split."""
        text = "A" * 6000
        chunks = _chunk_novel_text(text, max_chars=2000)
        assert len(chunks) >= 3
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_thai_text_chunking(self):
        """Thai text (no spaces) is split correctly at paragraph boundaries."""
        # Each paragraph ~2750 chars, which fits within max_chars=3000
        # So the \n\n split produces exactly 2 chunks
        thai_paragraph = "สวัสดีครับ " * 250  # ~2750 chars
        text = f"{thai_paragraph}\n\n{thai_paragraph}"
        chunks = _chunk_novel_text(text, max_chars=3000)
        assert len(chunks) == 2

    def test_real_world_novel_size(self):
        """Simulate a 50,000-char novel split into ~17 chunks."""
        paragraphs = [f"Chapter {i}. " + "x" * 2900 for i in range(17)]
        text = "\n\n".join(paragraphs)
        chunks = _chunk_novel_text(text, max_chars=3000)
        assert len(chunks) >= 15
        assert all(chunk.strip() for chunk in chunks)


class TestSplitLongParagraph:
    """Tests for _split_long_paragraph helper."""

    def test_sentence_split(self):
        """Splits by sentences when possible."""
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        parts = _split_long_paragraph(text, max_chars=30)
        assert len(parts) >= 2
        for part in parts:
            assert len(part) <= 35  # slight tolerance

    def test_hard_split_fallback(self):
        """Falls back to hard character split for text without sentence boundaries."""
        text = "a" * 6000  # No sentence boundaries
        parts = _split_long_paragraph(text, max_chars=2000)
        assert len(parts) == 3
        assert all(len(p) <= 2000 for p in parts)


# ── Multi-Part Scene Assignment ────────────────────────────────────────────────


class TestMultiPartScenes:
    """Tests for multi-part scene assignment in DB models."""

    def test_scene_has_part_number_default(self, db):
        """Scene defaults to part_number=1."""
        novel = Novel(title="Test", text="Some text", status="pending")
        db.add(novel)
        db.commit()

        scene = Scene(
            novel_id=novel.id,
            scene_number=1,
            scene_text="First scene",
        )
        db.add(scene)
        db.commit()
        db.refresh(scene)

        assert scene.part_number == 1

    def test_scene_custom_part_number(self, db):
        """Scene can be assigned to a specific part."""
        novel = Novel(title="Test", text="Some text", status="pending")
        db.add(novel)
        db.commit()

        scene = Scene(
            novel_id=novel.id,
            scene_number=50,
            scene_text="Scene in part 3",
            part_number=3,
        )
        db.add(scene)
        db.commit()
        db.refresh(scene)

        assert scene.part_number == 3

    def test_video_has_part_number(self, db):
        """Video record tracks part_number."""
        novel = Novel(title="Test", text="Some text", status="pending")
        db.add(novel)
        db.commit()

        video = Video(novel_id=novel.id, part_number=2, status="pending")
        db.add(video)
        db.commit()
        db.refresh(video)

        assert video.part_number == 2

    def test_multiple_videos_per_novel(self, db):
        """A single novel can have multiple video parts."""
        novel = Novel(title="Long Novel", text="x" * 10000, status="pending")
        db.add(novel)
        db.commit()

        for part in range(1, 4):
            video = Video(novel_id=novel.id, part_number=part, status="pending")
            db.add(video)
        db.commit()

        videos = db.query(Video).filter(Video.novel_id == novel.id).order_by(Video.part_number).all()
        assert len(videos) == 3
        assert [v.part_number for v in videos] == [1, 2, 3]

    def test_scenes_grouped_by_part(self, db):
        """Scenes can be queried by part_number."""
        novel = Novel(title="Test", text="Some text", status="pending")
        db.add(novel)
        db.commit()

        for i in range(1, 11):
            part = 1 if i <= 5 else 2
            scene = Scene(
                novel_id=novel.id,
                scene_number=i,
                scene_text=f"Scene {i}",
                part_number=part,
            )
            db.add(scene)
        db.commit()

        part1 = db.query(Scene).filter(
            Scene.novel_id == novel.id, Scene.part_number == 1
        ).all()
        part2 = db.query(Scene).filter(
            Scene.novel_id == novel.id, Scene.part_number == 2
        ).all()

        assert len(part1) == 5
        assert len(part2) == 5


# ── SceneData Model ───────────────────────────────────────────────────────────


class TestSceneDataModel:
    """Tests for the updated SceneData pydantic model."""

    def test_scene_data_default_part(self):
        sd = SceneData(scene_number=1, text="hi", image_prompt="img")
        assert sd.part == 1

    def test_scene_data_custom_part(self):
        sd = SceneData(scene_number=5, text="hi", image_prompt="img", part=3)
        assert sd.part == 3


# ── Resource Management ───────────────────────────────────────────────────────


class TestResourceManagement:
    """Tests for disk space and configuration limits."""

    def test_config_has_long_content_settings(self):
        """Settings class includes all long-content configuration."""
        from app.config import Settings

        s = Settings()
        assert hasattr(s, "llm_chunk_max_chars")
        assert hasattr(s, "max_scenes_per_part")
        assert hasattr(s, "max_total_scenes")
        assert hasattr(s, "image_task_concurrency")
        assert hasattr(s, "voice_task_concurrency")
        assert hasattr(s, "min_free_disk_gb")
        assert hasattr(s, "cleanup_clips_after_build")
        assert hasattr(s, "ffmpeg_max_workers")

    def test_config_defaults_are_reasonable(self):
        """Default values make sense for production."""
        from app.config import Settings

        s = Settings()
        assert s.llm_chunk_max_chars >= 1000
        assert s.max_scenes_per_part >= 50
        assert s.max_total_scenes >= 100
        assert s.image_task_concurrency >= 1
        assert s.voice_task_concurrency >= 1
        assert s.min_free_disk_gb >= 1.0
        assert s.ffmpeg_max_workers >= 1
