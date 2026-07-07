"""YouTubeChannel model — represents a YouTube channel linked to a topic."""
import uuid

from django.db import models


class YouTubeChannel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel_id = models.CharField(max_length=255, unique=True, help_text="YouTube Channel ID (e.g. UCxxxxx)")
    name = models.CharField(max_length=255)
    channel_url = models.URLField(max_length=500)
    topic = models.ForeignKey(
        "core.Topic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="youtube_channels",
        help_text="Admin assigns topic after channel creation",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "youtube_channel"
        ordering = ["name"]
        verbose_name = "YouTube Channel"
        verbose_name_plural = "YouTube Channels"

    def __str__(self):
        return self.name
