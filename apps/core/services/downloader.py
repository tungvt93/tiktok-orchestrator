"""Video downloader — downloads YouTube videos via yt-dlp."""
import logging
import os
import time
from pathlib import Path

import yt_dlp
from django.conf import settings

logger = logging.getLogger(__name__)

# Default download directory — override via Django settings
DOWNLOAD_DIR = Path(getattr(settings, "VIDEO_DOWNLOAD_DIR", "/tmp/video_downloads"))


def download_video(url: str, output_dir: Path | None = None) -> str:
    """
    Download a video from a YouTube URL using yt-dlp.

    Args:
        url: YouTube video URL (watch or shorts format).
        output_dir: Optional custom output directory.

    Returns:
        Absolute path to the downloaded MP4 file.

    Raises:
        RuntimeError: if download fails.
    """
    target_dir = output_dir or DOWNLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    output_template = str(target_dir / f"yt_{timestamp}_%(id)s.%(ext)s")

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    logger.info("Downloading video: %s", url)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            # Handle extension change during merge
            base, _ = os.path.splitext(filename)
            expected_mp4 = base + ".mp4"
            if os.path.exists(expected_mp4):
                filename = expected_mp4

        logger.info("Download complete: %s", filename)
        return filename
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(f"Download failed for {url}: {e}") from e
