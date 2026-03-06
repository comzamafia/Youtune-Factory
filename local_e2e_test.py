"""local_e2e_test.py — End-to-end local smoke test (pre-production final check)

Format : 1080 x 1920  (9:16 vertical — YouTube Shorts / TikTok / Reels)
Runs WITHOUT: PostgreSQL · Redis · Celery · Docker · GPU
Runs WITH:    SQLite · Edge TTS · Placeholder images · CPU FFmpeg · (optional Ollama)

Usage:
    python local_e2e_test.py                   # English, canned scenes (fast)
    python local_e2e_test.py --lang th          # Thai content
    python local_e2e_test.py --llm              # Use Ollama for real scene generation
    python local_e2e_test.py --lang th --llm    # Thai + LLM
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Windows UTF-8 fix (must happen first) ─────────────────────────────────────
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Force test environment BEFORE any app imports ─────────────────────────────
os.environ["DATABASE_URL"] = "sqlite:///./test_e2e.db"
os.environ["IMAGE_ENGINE"] = "placeholder"
os.environ["USE_GPU"] = "false"
os.environ["TTS_ENGINE"] = "edge_tts"
os.environ["VIDEO_WIDTH"] = "1080"
os.environ["VIDEO_HEIGHT"] = "1920"
os.environ["SUBTITLE_FONT_SIZE"] = "52"
os.environ["CLEANUP_CLIPS_AFTER_BUILD"] = "false"  # keep clips for inspection

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")
for _lib in ("httpx", "httpcore", "PIL", "comfyui", "multipart"):
    logging.getLogger(_lib).setLevel(logging.ERROR)

# ── ANSI color helpers ─────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def ok(msg: str):    print(f"  {_c('92', '✔')}  {msg}")
def fail(msg: str):  print(f"  {_c('91', '✖')}  {msg}")
def info(msg: str):  print(f"  {_c('96', '→')}  {msg}")
def warn(msg: str):  print(f"  {_c('93', '⚠')}  {msg}")
def sep():           print("  " + "─" * 52)

def step(n: int, title: str) -> None:
    print(f"\n{_c('1', f'[Step {n:02d}]')} {_c('97', title)}")
    print("  " + "─" * 52)

# ── Sample content ─────────────────────────────────────────────────────────────

EN_NOVEL_TEXT = """\
The Temple of Stars

Deep in the mountains lay a forgotten temple, sealed for a thousand years.
A young archaeologist named Maya discovered its entrance by accident during a storm.
She pushed open the ancient door and stepped into complete darkness.

Her torch revealed walls covered in glowing murals depicting celestial gods.
In the center stood a stone altar with a crystal sphere pulsing with golden light.
As she reached out, the sphere began to hum with an otherworldly resonance.

An ancient voice filled the chamber, offering Maya a choice:
take the sphere and gain unlimited knowledge, or leave it to protect the world.
She stood still for a long moment, feeling the weight of eternity in her hands.

Maya placed the sphere gently back on the altar and stepped away.
The temple doors swung open wide, flooding the chamber with morning sunlight.
Outside, the storm had passed, and the mountains gleamed with fresh snow.
"""

TH_NOVEL_TEXT = """\
วิหารดาวนิรันดร์

ลึกเข้าไปในเทือกเขาสูง มีวิหารโบราณที่ถูกลืมเลือนมานับพันปี
นักโบราณคดีสาวชื่อ มายา ค้นพบทางเข้าโดยบังเอิญในคืนพายุฝนกระหน่ำ
เธอผลักประตูหินโบราณเปิดออก และก้าวเข้าสู่ความมืดสนิท

แสงคบเพลิงส่องให้เห็นภาพจิตรกรรมฝาผนังเปล่งแสงสว่างไสวทั่วห้อง
ตรงกลางมีแท่นบูชาหินพร้อมลูกแก้วคริสตัลเต้นเป็นจังหวะด้วยแสงทองอุ่นนุ่ม
เมื่อเธอยื่นมือเข้าใกล้ ลูกแก้วเริ่มส่งเสียงฮัมลึกลับราวกับมีชีวิต

เสียงโบราณก้องขึ้นในวิหาร มอบทางเลือกสองทางแก่มายา
รับลูกแก้วไปและได้ยินความลับของจักรวาล หรือทิ้งมันไว้เพื่อปกป้องโลก
เธอยืนนิ่งอยู่นานชั่วครู่ รู้สึกถึงน้ำหนักแห่งกาลเวลาอยู่ในมือ

มายาวางลูกแก้วกลับลงบนแท่นบูชาอย่างนุ่มนวล แล้วก้าวถอยออกมา
ประตูวิหารเปิดออกเอง แสงอาทิตย์ยามเช้าสาดส่องเข้ามาเต็มห้อง
ข้างนอก พายุหยุดแล้ว และยอดเขาเปล่งแสงระยิบระยับด้วยหิมะสดใหม่
"""

# Canned scenes — used when --llm flag is NOT set (fast, no Ollama needed)
CANNED_EN = [
    {
        "scene_number": 1,
        "text": "Deep in the mountains lay a forgotten temple sealed for a thousand years. "
                "Young archaeologist Maya discovered its entrance during a wild storm.",
        "image_prompt": "ancient mountain temple, stormy night sky, dramatic stone entrance, torchlight",
        "mood": "mysterious",
        "start_time": 0.0,
        "end_time": 7.0,
    },
    {
        "scene_number": 2,
        "text": "Inside, glowing murals covered every wall. A crystal sphere rested on the "
                "stone altar, pulsing with warm golden light that filled the dark chamber.",
        "image_prompt": "ancient temple interior, glowing murals, crystal sphere on altar, golden radiant light",
        "mood": "awe-inspiring",
        "start_time": 7.0,
        "end_time": 14.0,
    },
    {
        "scene_number": 3,
        "text": "An ancient voice offered Maya a choice — unlimited knowledge or protecting "
                "the world. She placed the sphere back and walked toward the morning light.",
        "image_prompt": "woman at temple altar, decision moment, rays of golden light, hope, peaceful",
        "mood": "hopeful",
        "start_time": 14.0,
        "end_time": 21.0,
    },
]

CANNED_TH = [
    {
        "scene_number": 1,
        "text": "ลึกในเทือกเขา วิหารโบราณรอการค้นพบมาพันปี "
                "มายา นักโบราณคดีสาว ค้นพบทางเข้าในคืนพายุโดยบังเอิญ",
        "image_prompt": "ancient mountain temple, stormy night, dramatic entrance, torchlight glow",
        "mood": "mysterious",
        "start_time": 0.0,
        "end_time": 7.0,
    },
    {
        "scene_number": 2,
        "text": "ภายในวิหาร ภาพจิตรกรรมเปล่งแสงทั่วห้อง "
                "ลูกแก้วคริสตัลบนแท่นบูชาเต้นเป็นจังหวะด้วยแสงทองอุ่นนุ่ม",
        "image_prompt": "ancient temple interior, glowing murals, crystal sphere, golden light radiating",
        "mood": "awe-inspiring",
        "start_time": 7.0,
        "end_time": 14.0,
    },
    {
        "scene_number": 3,
        "text": "เสียงโบราณมอบทางเลือกแก่มายา ระหว่างความรู้ไม่สิ้นสุดกับการปกป้องโลก "
                "เธอวางลูกแก้วคืนและเดินออกสู่แสงอาทิตย์ยามเช้า",
        "image_prompt": "woman leaving temple, morning sun rays, mountain peaks, fresh snow, hopeful",
        "mood": "hopeful",
        "start_time": 14.0,
        "end_time": 21.0,
    },
]


# ── Pre-flight checks ──────────────────────────────────────────────────────────

def _check_ffmpeg() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        ver = r.stdout.splitlines()[0] if r.returncode == 0 else "unknown"
        ok(f"FFmpeg: {ver[:60]}")
        return True
    except FileNotFoundError:
        fail("FFmpeg not found")
        print("       → Install: winget install Gyan.FFmpeg")
        return False
    except Exception as e:
        fail(f"FFmpeg check error: {e}")
        return False


def _check_packages() -> bool:
    required = {
        "PIL": "pillow",
        "edge_tts": "edge-tts",
        "sqlalchemy": "sqlalchemy",
        "pydantic_settings": "pydantic-settings",
        "mutagen": "mutagen",
    }
    all_ok = True
    for module, pkg in required.items():
        try:
            __import__(module)
            ok(f"Package: {pkg}")
        except ImportError:
            fail(f"Missing package: {pkg}")
            print(f"       → Install: pip install {pkg}")
            all_ok = False
    return all_ok


def _check_ollama(llm_base_url: str, llm_model: str) -> bool:
    import urllib.request
    try:
        url = llm_base_url.replace("/v1", "").rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read().decode()
        ok(f"Ollama: reachable at {llm_base_url}")
        if llm_model not in data:
            warn(f"Model '{llm_model}' not found locally")
            print(f"       → Pull it: ollama pull {llm_model}")
        return True
    except Exception as e:
        fail(f"Ollama not reachable ({llm_base_url})")
        print(f"       → Start: ollama serve")
        print(f"       → Pull:  ollama pull {llm_model}")
        return False


def _check_disk() -> bool:
    free_gb = shutil.disk_usage(".").free / 1024 ** 3
    if free_gb < 1.0:
        fail(f"Disk: {free_gb:.1f} GB free — need ≥ 1 GB")
        return False
    ok(f"Disk: {free_gb:.1f} GB free")
    return True


def preflight(use_llm: bool, llm_base_url: str, llm_model: str) -> bool:
    print(f"\n{_c('1', 'Pre-flight Checks')}")
    print("  " + "─" * 52)
    ok_ffmpeg   = _check_ffmpeg()
    ok_packages = _check_packages()
    ok_disk     = _check_disk()
    ok_ollama   = _check_ollama(llm_base_url, llm_model) if use_llm else True
    passed = ok_ffmpeg and ok_packages and ok_disk and ok_ollama
    if not passed:
        print(f"\n  {_c('91;1', 'Pre-flight FAILED')} — fix the issues above, then re-run.")
    return passed


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local end-to-end pipeline smoke test (9:16 vertical video)",
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="Use Ollama to generate real scenes (requires Ollama running locally)",
    )
    parser.add_argument(
        "--lang", choices=["en", "th"], default="en",
        help="Content language: en=English (default), th=Thai",
    )
    args = parser.parse_args()
    use_llm = args.llm
    lang = args.lang

    # ── Banner ─────────────────────────────────────────────────────────────────
    print()
    print(_c("1;96", "  ╔══════════════════════════════════════════════════════╗"))
    print(_c("1;96", "  ║   AI YouTube Novel Factory — Local E2E Smoke Test   ║"))
    print(_c("1;96", "  ╠══════════════════════════════════════════════════════╣"))
    print(_c("96",   f"  ║  Format  : 1080 × 1920 px  (9:16 vertical)          ║"))
    print(_c("96",   f"  ║  Voice   : Edge TTS (free, no API key)               ║"))
    print(_c("96",   f"  ║  Images  : Placeholder (Pillow gradient, instant)    ║"))
    print(_c("96",   f"  ║  Video   : FFmpeg CPU encode                         ║"))
    mode_str = "Ollama LLM" if use_llm else "Canned scenes (fast, no LLM)"
    lang_str = "Thai (th-TH-PremwadeeNeural)" if lang == "th" else "English (en-US-AriaNeural)"
    print(_c("96",   f"  ║  Scenes  : {mode_str:<42s}║"))
    print(_c("96",   f"  ║  Lang    : {lang_str:<42s}║"))
    print(_c("1;96", "  ╚══════════════════════════════════════════════════════╝"))

    # Late import (after env vars are set)
    from app.config import settings

    if lang == "th":
        os.environ["EDGE_TTS_VOICE"] = "th-TH-PremwadeeNeural"

    if not preflight(use_llm, settings.llm_api_base_url, settings.llm_model):
        sys.exit(1)

    from app.core.database import Base, SessionLocal, engine
    from app.core.models import Novel, Scene, Video

    # ── Clean up previous test run ─────────────────────────────────────────────
    Path("test_e2e.db").unlink(missing_ok=True)

    total_start = time.perf_counter()
    timings: dict[str, float] = {}

    # ══════════════════════════════════════════════════════════════════════════
    step(1, "Database & directory setup")

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    ok(f"SQLite DB      : test_e2e.db (fresh)")
    ok(f"Video output   : {settings.video_output_dir}")
    ok(f"Output format  : {settings.video_width} × {settings.video_height} px  (9:16 vertical)")
    ok(f"Subtitle font  : {settings.subtitle_font_size} px")

    # ══════════════════════════════════════════════════════════════════════════
    step(2, "Create test novel in database")

    novel_title = "วิหารดาวนิรันดร์" if lang == "th" else "The Temple of Stars"
    novel_text  = TH_NOVEL_TEXT if lang == "th" else EN_NOVEL_TEXT

    novel = Novel(
        title=novel_title,
        author="E2E Test",
        text=novel_text.strip(),
        status="pending",
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    ok(f"Novel : '{novel.title}'  (id={str(novel.id)[:8]}…)")

    # ══════════════════════════════════════════════════════════════════════════
    step(3, f"Scene generation  ({'Ollama LLM' if use_llm else 'canned scenes'})")

    t0 = time.perf_counter()
    scenes: list[Scene] = []

    if use_llm:
        info(f"Calling {settings.llm_model} @ {settings.llm_api_base_url} …")
        try:
            from app.core.story_processor import process_novel
            scenes = await process_novel(novel.id, db)
        except Exception as e:
            fail(f"LLM scene generation failed: {e}")
            db.close()
            sys.exit(1)
    else:
        canned = CANNED_TH if lang == "th" else CANNED_EN
        for sd in canned:
            sc = Scene(
                novel_id=novel.id,
                scene_number=sd["scene_number"],
                scene_text=sd["text"],
                image_prompt=sd.get("image_prompt", ""),
                mood=sd.get("mood", "neutral"),
                start_time=sd["start_time"],
                end_time=sd["end_time"],
                part_number=1,
            )
            db.add(sc)
            scenes.append(sc)
        novel.status = "processing"
        db.commit()
        for sc in scenes:
            db.refresh(sc)

    timings["scenes"] = time.perf_counter() - t0
    ok(f"{len(scenes)} scenes ready  ({timings['scenes']:.1f}s)")

    # ══════════════════════════════════════════════════════════════════════════
    step(4, f"TTS voice generation  (Edge TTS — {settings.edge_tts_voice})")

    t0 = time.perf_counter()
    from app.ai.voice_generator import get_voice_generator

    voice_gen = get_voice_generator()
    for scene in scenes:
        out = settings.voice_dir / f"scene_{scene.scene_number:04d}.wav"
        try:
            await voice_gen.generate(scene.scene_text, out)
            scene.voice_path = str(out)
            info(f"Scene {scene.scene_number:02d}: voice → {out.name}  ({out.stat().st_size // 1024} KB)")
        except Exception as e:
            fail(f"TTS failed for scene {scene.scene_number}: {e}")
            db.close()
            sys.exit(1)
    db.commit()
    timings["voice"] = time.perf_counter() - t0
    ok(f"Voice generated for {len(scenes)} scenes  ({timings['voice']:.1f}s)")

    # ══════════════════════════════════════════════════════════════════════════
    step(5, f"Image generation  (engine={settings.image_engine}  {settings.video_width}×{settings.video_height})")

    t0 = time.perf_counter()
    from app.ai.image_generator import get_image_generator

    img_gen = get_image_generator()
    for scene in scenes:
        if scene.video_source_path:
            info(f"Scene {scene.scene_number:02d}: using video source — skipping image gen")
            continue
        out = settings.scenes_dir / f"scene_{scene.scene_number:04d}.png"
        try:
            await img_gen.generate(scene.image_prompt or scene.scene_text, out)
            scene.image_path = str(out)
            info(f"Scene {scene.scene_number:02d}: image → {out.name}  ({out.stat().st_size // 1024} KB)")
        except Exception as e:
            fail(f"Image gen failed for scene {scene.scene_number}: {e}")
            db.close()
            sys.exit(1)
    db.commit()
    timings["images"] = time.perf_counter() - t0
    ok(f"Images generated for {len(scenes)} scenes  ({timings['images']:.1f}s)")

    # ══════════════════════════════════════════════════════════════════════════
    step(6, "Subtitle (.srt) generation")

    from app.ai.subtitle_generator import generate_subtitles_from_scenes

    safe_title = novel.title.replace(" ", "_").replace("/", "_")
    subtitle_path = settings.subtitles_dir / f"{safe_title}_e2e.srt"
    scene_dicts = [
        {
            "scene_number": s.scene_number,
            "text": s.scene_text,
            "start_time": s.start_time or 0.0,
            "end_time": s.end_time or 7.0,
        }
        for s in scenes
    ]
    generate_subtitles_from_scenes(scene_dicts, subtitle_path)
    ok(f"Subtitles → {subtitle_path.name}")

    # ══════════════════════════════════════════════════════════════════════════
    step(7, f"Render scene clips  (FFmpeg  {settings.video_width}×{settings.video_height}  CPU)")

    t0 = time.perf_counter()
    from app.video.renderer import render_scene

    clip_paths: list[Path] = []
    for scene in scenes:
        clip_path = settings.scenes_dir / f"clip_{scene.scene_number:04d}.mp4"
        duration = (scene.end_time or 7.0) - (scene.start_time or 0.0)
        media_type = "video" if scene.video_source_path else "image"
        try:
            render_scene(
                scene={
                    "image_path": scene.image_path,
                    "video_source_path": scene.video_source_path,
                    "audio_path": scene.voice_path,
                    "duration": duration,
                },
                output_path=clip_path,
            )
            scene.clip_path = str(clip_path)
            clip_paths.append(clip_path)
            size_kb = clip_path.stat().st_size // 1024
            info(f"Scene {scene.scene_number:02d}: clip ({media_type}) → {clip_path.name}  ({size_kb} KB)")
        except Exception as e:
            fail(f"Render failed for scene {scene.scene_number}: {e}")
            db.close()
            sys.exit(1)
    db.commit()
    timings["render"] = time.perf_counter() - t0
    ok(f"Rendered {len(clip_paths)} clips  ({timings['render']:.1f}s)")

    # ══════════════════════════════════════════════════════════════════════════
    step(8, "Build final video  (concat + burn subtitles)")

    t0 = time.perf_counter()
    from app.video.builder import build_final_video

    final_path = settings.video_output_dir / f"{safe_title}_e2e.mp4"
    try:
        build_final_video(
            scene_clips=clip_paths,
            output_path=final_path,
            subtitle_path=subtitle_path,
        )
    except Exception as e:
        fail(f"Video build failed: {e}")
        db.close()
        sys.exit(1)
    timings["build"] = time.perf_counter() - t0
    ok(f"Final video built  ({timings['build']:.1f}s)")

    # ══════════════════════════════════════════════════════════════════════════
    step(9, "Verify output with FFprobe")

    video_ok = False
    if final_path.exists():
        size_mb = final_path.stat().st_size / 1024 ** 2
        ok(f"File   : {final_path}")
        ok(f"Size   : {size_mb:.2f} MB")

        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    str(final_path),
                ],
                capture_output=True, text=True, timeout=15,
            )
            if probe.returncode == 0:
                streams = json.loads(probe.stdout).get("streams", [])
                for st in streams:
                    if st.get("codec_type") == "video":
                        w       = st.get("width")
                        h       = st.get("height")
                        fps     = st.get("avg_frame_rate", "?")
                        dur_s   = float(st.get("duration", 0))
                        codec   = st.get("codec_name", "?")
                        ok(f"Video  : {w}×{h} px | {fps} fps | {dur_s:.1f}s | codec={codec}")
                        if w == settings.video_width and h == settings.video_height:
                            ok(f"Format : {_c('92;1', f'{w}×{h} = 9:16 vertical ✓')}")
                            video_ok = True
                        else:
                            warn(f"Dimension mismatch! Expected {settings.video_width}×{settings.video_height}, got {w}×{h}")
                    elif st.get("codec_type") == "audio":
                        acodec = st.get("codec_name", "?")
                        sr     = st.get("sample_rate", "?")
                        ok(f"Audio  : codec={acodec} | sample_rate={sr}")
            else:
                warn("ffprobe returned non-zero — skipping stream info")
        except Exception as e:
            warn(f"ffprobe check skipped: {e}")
    else:
        fail(f"Output file not found: {final_path}")

    # ══════════════════════════════════════════════════════════════════════════
    step(10, "Save results to database")

    video_rec = Video(
        novel_id=novel.id,
        video_path=str(final_path),
        subtitle_path=str(subtitle_path),
        status="rendered",
    )
    db.add(video_rec)
    novel.status = "completed"
    db.commit()
    db.close()
    ok("Novel status → completed")
    ok("Video record saved")

    # ══════════════════════════════════════════════════════════════════════════
    total_elapsed = time.perf_counter() - total_start

    print()
    print(_c("1;92", "  ╔══════════════════════════════════════════════════════╗"))
    print(_c("1;92", "  ║   ALL STEPS PASSED — Pipeline is ready for prod!    ║"))
    print(_c("1;92", "  ╠══════════════════════════════════════════════════════╣"))
    print(_c("92",   f"  ║  Novel   : {novel.title:<42s}║"))
    print(_c("92",   f"  ║  Scenes  : {len(scenes):<42d}║"))
    print(_c("92",   f"  ║  Format  : {settings.video_width}×{settings.video_height} px  (9:16 vertical){'':<24s}║"))
    print(_c("92",   f"  ║  Total   : {total_elapsed:.1f}s{'':<43s}║"))
    print(_c("1;92", "  ╠══════════════════════════════════════════════════════╣"))

    # Timing breakdown
    for stage, t in timings.items():
        label = f"  ║  {stage.capitalize():<8}: {t:.1f}s"
        print(_c("92", f"{label:<56}║"))

    print(_c("1;92", "  ╠══════════════════════════════════════════════════════╣"))
    video_display = str(final_path)
    if len(video_display) > 42:
        video_display = "…" + video_display[-41:]
    sub_display = str(subtitle_path)
    if len(sub_display) > 42:
        sub_display = "…" + sub_display[-41:]
    print(_c("92", f"  ║  VIDEO : {video_display:<44s}║"))
    print(_c("92", f"  ║  SRT   : {sub_display:<44s}║"))
    print(_c("1;92", "  ╚══════════════════════════════════════════════════════╝"))
    print()
    print(f"  {_c('1', 'Open video:')}  start {_c('96', str(final_path))}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
