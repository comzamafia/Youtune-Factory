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
import os
import sys


def main():
    # Railway injects PORT as env var; use it as default so no shell expansion needed
    default_port = int(os.environ.get("PORT", "8000"))

    parser = argparse.ArgumentParser(
        description="AI YouTube Novel Factory — Novel to YouTube pipeline"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=default_port, help="Server port (default: PORT env or 8000)")
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
