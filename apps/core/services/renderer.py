"""Video renderer service — processes video with zoom, speed changes, and appends a random outro."""
import logging
import os
import random
import subprocess
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)


def render_video_with_outro(video_path: str, speed: float = 1.05, zoom: float = 1.05) -> str:
    """
    Render a video for TikTok:
    - Speed up by 'speed' factor (e.g. 1.05x).
    - Zoom in by 'zoom' factor (e.g. 1.05x).
    - Convert to vertical 9:16 aspect ratio (1080x1920).
    - Append a random outro video from the outros/ directory.

    Args:
        video_path: Absolute path to the downloaded YouTube video.
        speed: Speed multiplier.
        zoom: Zoom factor.

    Returns:
        Absolute path to the rendered video file.
    """
    # Define and create outros directory at project root
    outro_dir = Path(settings.BASE_DIR) / "outros"
    outro_dir.mkdir(exist_ok=True)

    # 1. Find all MP4 outros in the directory
    outros = list(outro_dir.glob("*.mp4"))
    if not outros:
        raise FileNotFoundError(
            f"Không tìm thấy file outro .mp4 nào trong thư mục: {outro_dir}. "
            f"Vui lòng thêm ít nhất một video outro vào thư mục này."
        )

    selected_outro = str(random.choice(outros))
    logger.info("Selected random outro: %s", selected_outro)

    # Generate output path
    base, ext = os.path.splitext(video_path)
    output_path = f"{base}_rendered.mp4"

    # TikTok standard dimensions
    target_w = 1080
    target_h = 1920

    # Calculate zoomed dimensions
    zoomed_w = int(target_w * zoom)
    zoomed_h = int(target_h * zoom)

    # Filter complex explanation:
    # [0:v] -> scale & crop to 1080x1920 -> scale up to zoomed dimensions -> crop back to 1080x1920 -> setpts for speed
    # [0:a] -> atempo for speed
    # [1:v] -> scale & crop to 1080x1920
    # [1:a] -> format to match sample rate and channel layout
    # concat -> concatenates both parts
    filter_complex = (
        # Process main video (zoom, scale/crop, speedup)
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},"
        f"scale={zoomed_w}:{zoomed_h},"
        f"crop={target_w}:{target_h},"
        f"setpts=PTS/{speed}[v0]; "
        f"[0:a]atempo={speed}[a0]; "
        # Process outro video (scale/crop)
        f"[1:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}[v1]; "
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1]; "
        # Concat the two videos
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", selected_outro,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        output_path
    ]

    logger.info("Executing FFmpeg render command for video: %s", video_path)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        logger.error("FFmpeg render failed with exit code %d. Stderr: %s", result.returncode, result.stderr)
        raise RuntimeError(f"FFmpeg rendering error: {result.stderr}")

    logger.info("Successfully rendered video: %s", output_path)
    return output_path
