"""AI YouTube Novel Factory — Entry point.

Usage:
    # Start API server
    python main.py

    # Start API server with custom host/port
    python main.py --host 0.0.0.0 --port 8080

    # Start Celery workers (in separate terminals)
    celery -A app.core.celery_app worker -Q script --loglevel=info
    celery -A app.core.celery_app worker -Q tts --loglevel=info
    celery -A app.core.celery_app worker -Q image --loglevel=info
    celery -A app.core.celery_app worker -Q video --loglevel=info
    celery -A app.core.celery_app worker -Q upload --loglevel=info
"""

from __future__ import annotations

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="AI YouTube Novel Factory — Novel to YouTube pipeline"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    import uvicorn

    print(
        "\n"
        "  +-----------------------------------------------+\n"
        "  |   AI YouTube Novel Factory  v1.0.0           |\n"
        "  |   Novel -> Script -> Voice -> Image -> Video  |\n"
        "  +-----------------------------------------------+\n"
    )

    uvicorn.run(
        "app.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
