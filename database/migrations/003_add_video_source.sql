-- Migration 003: Add video_source_path to scenes table
-- Run: psql $DATABASE_URL -f database/migrations/003_add_video_source.sql

ALTER TABLE scenes ADD COLUMN IF NOT EXISTS video_source_path TEXT;
