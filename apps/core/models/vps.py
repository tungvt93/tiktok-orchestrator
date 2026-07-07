"""VPS model — represents a VPS instance with TikTok upload API endpoint."""
import uuid

from django.db import models


class VPS(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    host = models.CharField(max_length=255)
    api_endpoint = models.URLField(max_length=500)
    api_key = models.CharField(max_length=500, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vps"
        ordering = ["name"]
        verbose_name = "VPS"
        verbose_name_plural = "VPS"

    def __str__(self):
        return self.name
