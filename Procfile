# Procfile — defines named process types for Railway (or Heroku-style runners)
# Railway uses this when RAILWAY_SERVICE_NAME matches the process name.
#
# Each entry becomes a separate Railway service that shares the same Docker image
# but runs a different command.

# ── API Server ────────────────────────────────────────────────────────
api: python main.py --host 0.0.0.0 --port $PORT

# ── Celery Workers ────────────────────────────────────────────────────
worker-script: celery -A app.core.celery_app worker -Q script -n script@%h --loglevel=info --concurrency=2 --max-tasks-per-child=50
worker-tts:    celery -A app.core.celery_app worker -Q tts    -n tts@%h    --loglevel=info --concurrency=4 --max-tasks-per-child=100
worker-image:  celery -A app.core.celery_app worker -Q image   -n image@%h  --loglevel=info --concurrency=1 --max-tasks-per-child=20
worker-video:  celery -A app.core.celery_app worker -Q video   -n video@%h  --loglevel=info --concurrency=1 --max-tasks-per-child=10
worker-upload: celery -A app.core.celery_app worker -Q upload  -n upload@%h --loglevel=info --concurrency=1 --max-tasks-per-child=20

# ── Celery Beat (Scheduler) ───────────────────────────────────────────
beat: celery -A app.core.celery_app beat --loglevel=info
