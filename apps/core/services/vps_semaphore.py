"""VPS concurrency semaphore — limits simultaneous uploads per VPS via Redis."""
import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Lua script for atomic acquire: INCR → check ≤ max → DECR if full
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local max_slots = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('INCR', key)
if current <= max_slots then
    redis.call('EXPIRE', key, ttl)
    return 1
else
    redis.call('DECR', key)
    return 0
end
"""

# Lua script for atomic release
_RELEASE_SCRIPT = """
local key = KEYS[1]
local current = redis.call('GET', key)
if current and tonumber(current) > 0 then
    return redis.call('DECR', key)
else
    redis.call('DEL', key)
    return 0
end
"""

VPS_MAX_CONCURRENT_UPLOADS = 3
SEMAPHORE_TTL = 1800  # 30 minutes — prevents deadlock if worker crashes


def _get_redis():
    """Get a Redis connection from the configured URL."""
    return redis.Redis.from_url(settings.REDIS_URL)


def _semaphore_key(vps_id: str) -> str:
    """Build the Redis key for a VPS semaphore."""
    return f"vps:{vps_id}:active_uploads"


def acquire(vps_id: str, max_slots: int | None = None) -> bool:
    """
    Try to acquire an upload slot on a VPS.

    Args:
        vps_id: UUID string of the VPS.
        max_slots: Max concurrent uploads (default 3).

    Returns:
        True if a slot was acquired, False if VPS is at capacity.
    """
    if max_slots is None:
        max_slots = VPS_MAX_CONCURRENT_UPLOADS

    r = _get_redis()
    result = r.eval(_ACQUIRE_SCRIPT, 1, _semaphore_key(vps_id), max_slots, SEMAPHORE_TTL)

    if result == 1:
        logger.debug("VPS %s: slot acquired", vps_id)
        return True
    else:
        logger.debug("VPS %s: at capacity (%s slots)", vps_id, max_slots)
        return False


def release(vps_id: str) -> int:
    """
    Release an upload slot on a VPS.

    Args:
        vps_id: UUID string of the VPS.

    Returns:
        New count after decrement (0 if key was deleted).
    """
    r = _get_redis()
    result = r.eval(_RELEASE_SCRIPT, 1, _semaphore_key(vps_id))
    logger.debug("VPS %s: slot released, count now %s", vps_id, result)
    return result


def get_active_count(vps_id: str) -> int:
    """Return current active upload count for a VPS (for monitoring)."""
    r = _get_redis()
    val = r.get(_semaphore_key(vps_id))
    return int(val) if val else 0
