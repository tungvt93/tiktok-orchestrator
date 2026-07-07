"""TikTokProfile model — represents a TikTok profile on a specific VPS."""
import uuid

from django.db import models


class TikTokProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile_name = models.CharField(max_length=255)
    topic = models.ForeignKey(
        "core.Topic",
        on_delete=models.CASCADE,
        related_name="tiktok_profiles",
    )
    vps = models.ForeignKey(
        "core.VPS",
        on_delete=models.CASCADE,
        related_name="tiktok_profiles",
    )
    daily_video_limit = models.IntegerField(default=5)
    videos_today = models.IntegerField(default=0)
    last_upload_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tiktok_profile"
        ordering = ["profile_name"]
        verbose_name = "TikTok Profile"
        verbose_name_plural = "TikTok Profiles"

    def __str__(self):
        return f"{self.profile_name} ({self.vps.name})"
