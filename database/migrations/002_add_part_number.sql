-- AI YouTube Novel Factory — Add multi-part video support
-- Run: psql -U postgres -d aiyoutube -f 002_add_part_number.sql

BEGIN;

-- ── scenes: add part_number and index on scene_number ──────────────

ALTER TABLE scenes
    ADD COLUMN IF NOT EXISTS part_number INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_scenes_scene_number ON scenes (scene_number);
CREATE INDEX IF NOT EXISTS idx_scenes_part_number  ON scenes (part_number);

-- ── videos: add part_number ─────────────────────────────────────────

ALTER TABLE videos
    ADD COLUMN IF NOT EXISTS part_number INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_videos_part_number ON videos (part_number);

COMMIT;
