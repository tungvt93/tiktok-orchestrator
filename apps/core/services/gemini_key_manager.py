"""Gemini API key pool manager — quota-aware key selection and rotation."""
import logging
from django.utils import timezone
from django.db.models import F
from apps.core.models.gemini_api_key import GeminiAPIKey

logger = logging.getLogger(__name__)


class NoAvailableKeyError(Exception):
    """Raised when all Gemini API keys are exhausted for the day."""


def get_available_key() -> GeminiAPIKey:
    """
    Select the best Gemini API key with remaining daily quota.

    Priority: least-recently-used first (last_used_at ASC NULLS FIRST),
    then lowest usage count.

    Returns:
        GeminiAPIKey instance.

    Raises:
        NoAvailableKeyError: if no key has remaining quota.
    """
    key = (
        GeminiAPIKey.objects
        .filter(
            is_active=True,
            daily_usage_count__lt=F("daily_usage_limit"),
        )
        .order_by(
            F("last_used_at").asc(nulls_first=True),
            "daily_usage_count",
        )
        .first()
    )

    if key is None:
        raise NoAvailableKeyError(
            "No Gemini API key with remaining quota available. "
            "Add more keys or wait for daily reset."
        )

    return key


def increment_usage(key: GeminiAPIKey) -> None:
    """
    Increment the daily usage counter and update last_used_at.

    Uses update() to avoid race conditions — skips the ORM save cycle.
    """
    GeminiAPIKey.objects.filter(id=key.id).update(
        daily_usage_count=F("daily_usage_count") + 1,
        last_used_at=timezone.now(),
    )
    logger.info(
        "Gemini key %s: %s/%s calls used today",
        str(key),
        key.daily_usage_count + 1,  # approximate; actual value is F()+1 in DB
        key.daily_usage_limit,
    )
