"""Config helper — reads values from the SystemConfig database table."""
from apps.core.models.system_config import SystemConfig


def get_config(key, default=None):
    """
    Read a configuration value from the SystemConfig model.

    Returns the string value stored in the database for the given key.
    If the key does not exist, returns the provided default.

    Callers are responsible for type coercion (e.g., int(), bool()).
    """
    try:
        return SystemConfig.objects.get(key=key).value
    except SystemConfig.DoesNotExist:
        return default
