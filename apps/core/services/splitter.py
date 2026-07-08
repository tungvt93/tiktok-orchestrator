"""Gemini-powered video analyzer — finds highlight clips for splitting."""
import json
import logging
import random
import time
import subprocess
from typing import Any, Dict, List

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VideoClipHighlight(BaseModel):
    title: str = Field(description="Short engaging title for this clip")
    start_seconds: float = Field(description="Start time in seconds")
    end_seconds: float = Field(description="End time in seconds (must be > start_seconds)")
    reason: str = Field(description="Why this clip is engaging or has viral potential")


class HighlightAnalysisResult(BaseModel):
    clips: List[VideoClipHighlight]


def _parse_time_to_seconds(value: Any) -> float:
    """Parse timestamps in HH:MM:SS, MM:SS, or float format into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parts = value.strip().split(":")
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            else:
                return float(value)
        except ValueError:
            return 0.0
    return 0.0

def get_video_duration(input_file: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', input_file
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe failed to get duration: %s", e)
        return 180.0


def analyze_video_for_highlights(
    video_path: str,
    api_key: str,
    num_clips: int | None = None,
    min_clip_duration: float = 8.0,
    max_clip_duration: float = 20.0,
) -> List[Dict[str, Any]]:
    """
    Upload video to Gemini Files API and request highlight timestamps.

    Args:
        video_path: Local path to the downloaded video file.
        api_key: Gemini API key to use.
        num_clips: Number of highlight clips to extract.
        min_clip_duration: Minimum clip duration in seconds.
        max_clip_duration: Maximum clip duration in seconds.

    Returns:
        List of dicts with: clip_index, title, start_seconds, end_seconds,
        duration, reason.

    Raises:
        RuntimeError: if Gemini analysis fails after all retries.
    """
    client = genai.Client(api_key=api_key)

    logger.info("Uploading video to Gemini: %s", video_path)
    uploaded_file = client.files.upload(file=video_path)
    logger.info("Upload complete. File URI: %s. Waiting for processing...", uploaded_file.uri)

    # Poll until processing completes
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(4)
        uploaded_file = client.files.get(name=uploaded_file.name)
        logger.info("Processing status: %s", uploaded_file.state.name)

    if uploaded_file.state.name != "ACTIVE":
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
        raise RuntimeError(f"Video processing failed: {uploaded_file.state.name}")

    logger.info("Video ACTIVE. Sending analysis prompt (duration %ss-%ss)...", min_clip_duration, max_clip_duration)

    if num_clips is None:
        total_duration = get_video_duration(video_path)
        # 1 clip per 60 seconds, min 1, max 10
        num_clips = max(1, min(10, int(total_duration / 60)))
        logger.info("Video duration is %.1fs. Dynamically requesting %d clips.", total_duration, num_clips)

    duration_instruction = (
        f"2. Clip duration (end_seconds - start_seconds) MUST be between "
        f"{min_clip_duration}s and {max_clip_duration}s."
    )

    prompt = f"""
Analyze this video carefully and select exactly {num_clips} highlight moments that have the highest potential to go viral on short-form video platforms (TikTok, Reels, Shorts).

MANDATORY REQUIREMENTS:
1. NO OVERLAP in content or time: The [start_seconds, end_seconds] ranges across all clips must be completely separate — absolutely no overlap.
{duration_instruction}
3. Return results in standard JSON format.

VIRAL SELECTION CRITERIA (Prioritize segments with these elements):
- Strong Hook: The first 2-3 seconds of each clip must have high visual or auditory impact (e.g., a sudden action, a funny expression, a shocking statement, or an abrupt change) to grab immediate attention.
- Emotional Peaks: Moments that trigger strong emotional responses, such as high excitement, intense drama, genuine laughter, suspense, or extreme cuteness/satisfaction.
- Clear Context: Each clip should tell a mini-story or present a complete, understandable thought/action within its timeframe, so viewers don't feel confused.
- Sound & Visual Synchronization: Prefer segments where the background music drops, a loud sound effect occurs, or there is an energetic peak in dialogue/action.
"""

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]
    response = None
    last_error = None

    for model_name in models_to_try:
        for attempt in range(1, 4):
            try:
                logger.info("Sending to %s (attempt %d)...", model_name, attempt)
                response = client.models.generate_content(
                    model=model_name,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=HighlightAnalysisResult,
                        temperature=0.4,
                    ),
                )
                if response:
                    break
            except Exception as e:
                last_error = e
                err_msg = str(e)
                logger.warning("Error on %s attempt %d: %s", model_name, attempt, err_msg)
                if any(kw in err_msg for kw in ["503", "UNAVAILABLE", "high demand"]):
                    logger.info("Server overloaded. Waiting 5s...")
                    time.sleep(5)
                else:
                    break
        if response:
            break

    # Cleanup uploaded file
    try:
        client.files.delete(name=uploaded_file.name)
        logger.info("Cleaned up temp file from Gemini storage.")
    except Exception as e:
        logger.warning("Could not delete temp file: %s", e)

    if not response:
        raise RuntimeError(
            f"Gemini AI unreachable after all retries. Last error: {last_error}"
        )

    logger.info("Received response from Gemini.")

    try:
        result_data = json.loads(response.text)
        clips_raw = result_data.get("clips", [])
    except Exception as e:
        logger.error("Error parsing JSON response: %s. Raw: %s", e, response.text)
        clips_raw = []

    final_clips = []
    occupied_ranges: List[tuple] = []

    for clip in clips_raw:
        title = clip.get("title", f"Highlight #{len(final_clips) + 1}")
        start_s = _parse_time_to_seconds(clip.get("start_seconds", 0))
        end_s = _parse_time_to_seconds(clip.get("end_seconds", 0))
        reason = clip.get("reason", "")

        duration = end_s - start_s

        # Enforce duration bounds
        if duration < min_clip_duration or duration > max_clip_duration:
            target_duration = random.uniform(min_clip_duration, max_clip_duration)
            end_s = start_s + target_duration
            logger.info(
                "Adjusted duration from %.2fs to %.2fs (range %ss-%ss).",
                duration, target_duration, min_clip_duration, max_clip_duration,
            )

        # Check overlap
        is_overlapping = any(
            not (end_s <= occ_start or start_s >= occ_end)
            for occ_start, occ_end in occupied_ranges
        )

        if is_overlapping:
            logger.info(
                "Skipped overlapping clip '%s' [%.1fs-%.1fs].", title, start_s, end_s
            )
            continue

        occupied_ranges.append((start_s, end_s))
        final_clips.append({
            "clip_index": len(final_clips) + 1,
            "title": title,
            "start_seconds": round(start_s, 2),
            "end_seconds": round(end_s, 2),
            "duration": round(end_s - start_s, 2),
            "reason": reason,
        })

    return final_clips
