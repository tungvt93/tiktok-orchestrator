"""GeminiAPIKey model — pool of Gemini API keys with quota tracking."""
import uuid

from django.db import models


class GeminiAPIKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_key = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    daily_usage_count = models.IntegerField(default=0)
    daily_usage_limit = models.IntegerField(default=1400)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gemini_api_key"
        ordering = ["last_used_at"]
        verbose_name = "Gemini API Key"
        verbose_name_plural = "Gemini API Keys"

    def __str__(self):
        masked = self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
        return f"GeminiKey {masked} (used {self.daily_usage_count}/{self.daily_usage_limit})"
