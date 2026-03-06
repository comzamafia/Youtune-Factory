-- AI YouTube Novel Factory — Initial Database Migration
-- Run: psql -U postgres -d aiyoutube -f 001_initial.sql

BEGIN;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── novels ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS novels (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title       TEXT        NOT NULL,
    author      TEXT        NOT NULL DEFAULT 'Unknown',
    text        TEXT        NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_novels_status ON novels (status);

-- ── scenes ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scenes (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id     UUID        NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    scene_number INTEGER     NOT NULL,
    scene_text   TEXT        NOT NULL,
    start_time   FLOAT,
    end_time     FLOAT,
    image_prompt TEXT,
    mood         VARCHAR(50),
    voice_path   TEXT,
    image_path   TEXT,
    clip_path    TEXT,
    part_number  INTEGER     NOT NULL DEFAULT 1
);

CREATE INDEX idx_scenes_novel_id ON scenes (novel_id);
CREATE INDEX idx_scenes_part     ON scenes (novel_id, part_number);

-- ── videos ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS videos (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id      UUID        NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    part_number   INTEGER     NOT NULL DEFAULT 1,
    video_path    TEXT,
    subtitle_path TEXT,
    thumbnail     TEXT,
    youtube_url   TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'rendering', 'rendered', 'uploading', 'uploaded', 'failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_videos_novel_id ON videos (novel_id);
CREATE INDEX idx_videos_status   ON videos (status);

-- ── jobs ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jobs (
    job_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id      UUID REFERENCES novels(id) ON DELETE SET NULL,
    job_type      VARCHAR(50) NOT NULL
                      CHECK (job_type IN (
                          'generate_script', 'generate_voice', 'generate_image',
                          'render_video', 'generate_subtitle', 'generate_thumbnail',
                          'upload_youtube', 'full_pipeline'
                      )),
    status        VARCHAR(20) NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    priority      INTEGER     NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

CREATE INDEX idx_jobs_novel_id ON jobs (novel_id);
CREATE INDEX idx_jobs_status   ON jobs (status);

COMMIT;
