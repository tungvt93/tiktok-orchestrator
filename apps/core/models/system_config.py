"""SystemConfig model — key-value configuration store for runtime settings."""
import uuid

from django.db import models


class SystemConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, unique=True)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "system_config"
        ordering = ["key"]
        verbose_name = "System Config"
        verbose_name_plural = "System Configs"

    def __str__(self):
        return f"{self.key} = {self.value}"
