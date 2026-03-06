"""YouTube Uploader — Uploads videos via YouTube Data API v3."""

from __future__ import annotations

import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_authenticated_service():
    """Authenticate with YouTube and return the API service object."""
    creds = None
    creds_path = Path(settings.youtube_credentials_file)

    if creds_path.exists():
        creds = Credentials.from_authorized_user_file(str(creds_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.youtube_client_secret_file, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        creds_path.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "24",  # Entertainment
    thumbnail_path: Path | None = None,
    privacy_status: str = "private",
) -> str:
    """
    Upload a video to YouTube.

    Args:
        video_path: Path to the MP4 file.
        title: Video title.
        description: Video description.
        tags: List of tags.
        category_id: YouTube category ID (24 = Entertainment).
        thumbnail_path: Optional custom thumbnail JPEG.
        privacy_status: ``private``, ``unlisted``, or ``public``.

    Returns:
        The YouTube video URL.
    """
    youtube = _get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    logger.info("Uploading '%s' to YouTube…", title)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %d%%", int(status.progress() * 100))

    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Uploaded → %s", video_url)

    # Set custom thumbnail if provided
    if thumbnail_path and thumbnail_path.exists():
        thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=thumb_media,
        ).execute()
        logger.info("Custom thumbnail set for %s", video_id)

    return video_url
