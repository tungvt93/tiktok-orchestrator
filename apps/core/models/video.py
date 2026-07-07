"""Video model — represents a YouTube video tracked for TikTok distribution."""
import uuid

from django.db import models


class Video(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SPLITTING = "splitting", "Splitting"
        SPLIT = "split", "Split"
        PROCESSING = "processing", "Processing"
        UPLOADED = "uploaded", "Uploaded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video_id = models.CharField(max_length=255, unique=True, help_text="YouTube Video ID")
    video_url = models.URLField(max_length=500)
    youtube_channel = models.ForeignKey(
        "core.YouTubeChannel",
        on_delete=models.CASCADE,
        related_name="videos",
    )
    uploaded_to_profile = models.ForeignKey(
        "core.TikTokProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
    )
    uploaded_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    retry_count = models.IntegerField(default=0)
    error_log = models.TextField(null=True, blank=True)
    parent_video = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="split_parts",
    )
    part_number = models.IntegerField(null=True, blank=True)
    is_split_original = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "video"
        ordering = ["-created_at"]
        verbose_name = "Video"
        verbose_name_plural = "Videos"

    def __str__(self):
        return f"Video {self.video_id}"
