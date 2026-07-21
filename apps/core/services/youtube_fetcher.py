"""YouTube Fetcher service — fetches metadata for a channel's recent videos using yt-dlp."""
import logging
import yt_dlp

logger = logging.getLogger(__name__)


def fetch_recent_video_ids(channel_url: str, limit: int = 10) -> list[dict]:
    """
    Fetch recent video metadata for a YouTube channel URL without downloading.

    Args:
        channel_url: The URL of the YouTube channel.
        limit: Max number of videos to scan.

    Returns:
        List of dicts containing: video_id, title, url, view_count.
    """
    ydl_opts = {
        "extract_flat": True,
        "playlistend": limit,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        # Set a reasonable socket timeout to prevent hangs
        "socket_timeout": 20,
    }
    
    logger.info("Scanning YouTube channel: %s (limit=%d)", channel_url, limit)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # We fetch info without downloading
            info = ydl.extract_info(channel_url, download=False)
            if not info:
                logger.warning("No channel info returned for %s", channel_url)
                return []

            entries = info.get("entries", [])
            results = []
            for entry in entries:
                if not entry:
                    continue
                
                video_id = entry.get("id") or entry.get("video_id")
                if not video_id:
                    continue

                view_count = entry.get("view_count") or 0
                title = entry.get("title") or f"Video {video_id}"
                
                results.append({
                    "video_id": video_id,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "view_count": int(view_count),
                })
            
            logger.info("Successfully fetched %d video entries from channel %s", len(results), channel_url)
            return results
            
    except Exception as e:
        logger.exception("Error occurred while fetching YouTube channel videos for %s: %s", channel_url, e)
        return []
