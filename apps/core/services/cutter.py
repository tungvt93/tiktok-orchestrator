"""Video cutter — cuts MP4 clips from source video using FFmpeg."""
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from django.conf import settings

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(getattr(settings, "VIDEO_OUTPUT_DIR", "/tmp/video_outputs"))


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters for filesystem filenames."""
    s = re.sub(r"[^\w\s-]", "", filename).strip()
    return re.sub(r"[-\s]+", "_", s)


def cut_video_clips(
    video_path: str,
    clips: List[Dict[str, Any]],
    speed: float = 1.2,
    output_dir: Path | None = None,
) -> List[Dict[str, Any]]:
    """
    Cut video clips from input video using FFmpeg.

    Each clip dict must have: clip_index, title, start_seconds, end_seconds.
    On success, each returned clip gains: output_path, final_duration.

    Args:
        video_path: Path to the source video file.
        clips: List of clip definitions from Gemini analysis.
        speed: Speed multiplier for output (1.0 = original speed).
        output_dir: Optional custom output directory.

    Returns:
        The clips list with output_path and final_duration added for each
        successfully-cut clip.
    """
    target_dir = output_dir or OUTPUT_DIR
    timestamp = int(time.time())
    session_dir = target_dir / f"session_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting cut process for %d clips (speed %.1fx)...", len(clips), speed)
    processed = []

    for clip in clips:
        idx = clip.get("clip_index", 1)
        title = clip.get("title", f"clip_{idx}")
        start_s = clip.get("start_seconds", 0.0)
        end_s = clip.get("end_seconds", 10.0)
        orig_duration = end_s - start_s

        safe_title = sanitize_filename(title)[:30]
        out_filename = f"short_{idx}_{safe_title}.mp4"
        out_filepath = str(session_dir / out_filename)

        logger.info(
            "Cutting clip #%d (%.1fs-%.1fs, orig %.1fs, speed %.1fx) → %s",
            idx, start_s, end_s, orig_duration, speed, out_filename,
        )

        # Primary FFmpeg command with speed-up
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_s),
            "-to", str(end_s),
            "-i", video_path,
        ]

        if speed != 1.0:
            cmd.extend([
                "-vf", f"setpts=PTS/{speed}",
                "-af", f"atempo={speed}",
            ])

        cmd.extend([
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            out_filepath,
        ])

        try:
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
            )
            clip["output_path"] = out_filepath
            clip["final_duration"] = round(orig_duration / speed, 2)
            processed.append(clip)
            logger.info("Cut succeeded: %s", out_filepath)

        except subprocess.CalledProcessError as e:
            logger.warning("Cut failed for clip #%d: %s. Trying fallback...", idx, e.stderr)

            # Fallback: stream-copy without speed filters
            fallback_cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_s),
                "-to", str(end_s),
                "-i", video_path,
                "-c", "copy",
                out_filepath,
            ]
            try:
                subprocess.run(
                    fallback_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=True,
                )
                clip["output_path"] = out_filepath
                clip["final_duration"] = round(orig_duration, 2)
                processed.append(clip)
                logger.info("Fallback cut succeeded: %s", out_filepath)
            except Exception as ex:
                logger.error("Fallback cut failed for clip #%d: %s", idx, ex)

    logger.info("Cut complete: %d/%d clips processed.", len(processed), len(clips))
    return processed
