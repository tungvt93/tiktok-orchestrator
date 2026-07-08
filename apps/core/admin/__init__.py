"""Django Admin configuration for all core models."""
from django.contrib import admin

from apps.core.models import Topic, VPS, YouTubeChannel, TikTokProfile, Video, GeminiAPIKey
from django.utils.html import format_html
from django.urls import reverse
from django.contrib.admin.actions import delete_selected

# Rename global delete_selected action to Vietnamese
def custom_delete_selected(modeladmin, request, queryset):
    return delete_selected(modeladmin, request, queryset)
custom_delete_selected.short_description = "❌ Xóa các bản ghi đã chọn (Hàng loạt)"

admin.site.disable_action("delete_selected")
admin.site.add_action(custom_delete_selected, "delete_selected")

class DeleteActionMixin:
    @admin.display(description="Action")
    def delete_button(self, obj):
        if not obj.pk:
            return ""
        url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_delete", args=[obj.pk])
        return format_html(
            '<a class="button" style="background-color: #ba2121; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none;" href="{}">Xóa</a>', 
            url
        )


# ── Topic ──────────────────────────────────────────────────────────────

@admin.register(Topic)
class TopicAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = ["name", "slug", "channel_count", "profile_count", "created_at", "delete_button"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Channels")
    def channel_count(self, obj):
        return obj.youtube_channels.count()

    @admin.display(description="Profiles")
    def profile_count(self, obj):
        return obj.tiktok_profiles.count()


# ── YouTubeChannel ─────────────────────────────────────────────────────

@admin.register(YouTubeChannel)
class YouTubeChannelAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = ["name", "channel_id", "topic", "is_active", "video_count", "created_at", "delete_button"]
    list_filter = ["is_active", "topic"]
    search_fields = ["name", "channel_id"]
    list_editable = ["topic", "is_active"]
    autocomplete_fields = ["topic"]

    @admin.display(description="Videos")
    def video_count(self, obj):
        return obj.videos.count()


# ── VPS ────────────────────────────────────────────────────────────────

@admin.register(VPS)
class VPSAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = ["name", "host", "is_active", "profile_count", "created_at", "delete_button"]
    list_filter = ["is_active"]
    search_fields = ["name", "host", "api_endpoint"]
    list_editable = ["is_active"]

    @admin.display(description="Profiles")
    def profile_count(self, obj):
        return obj.tiktok_profiles.count()


# ── TikTokProfile ──────────────────────────────────────────────────────

@admin.register(TikTokProfile)
class TikTokProfileAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = [
        "profile_name", "topic", "vps", "is_active",
        "videos_today", "daily_video_limit", "capacity_status",
        "last_upload_at", "created_at", "delete_button"
    ]
    list_filter = ["is_active", "topic", "vps"]
    search_fields = ["profile_name"]
    list_editable = ["is_active", "daily_video_limit"]
    autocomplete_fields = ["topic", "vps"]
    actions = ["reset_daily_counters"]

    @admin.display(description="Capacity")
    def capacity_status(self, obj):
        used = obj.videos_today
        limit = obj.daily_video_limit
        if used >= limit:
            return f"🔴 {used}/{limit} FULL"
        if used >= limit * 0.8:
            return f"🟡 {used}/{limit}"
        return f"🟢 {used}/{limit}"

    @admin.action(description="Reset videos_today to 0 for selected profiles")
    def reset_daily_counters(self, request, queryset):
        updated = queryset.update(videos_today=0)
        self.message_user(request, f"Reset counters for {updated} profile(s).")


# ── Gemini API Key ─────────────────────────────────────────────────────

@admin.register(GeminiAPIKey)
class GeminiAPIKeyAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = ["masked_key", "is_active", "usage_display", "last_used_at", "created_at", "delete_button"]
    list_filter = ["is_active"]
    list_editable = ["is_active"]
    search_fields = ["api_key"]
    actions = ["reset_usage_counters"]

    @admin.display(description="API Key")
    def masked_key(self, obj):
        return obj.api_key[:10] + "..." if len(obj.api_key) > 10 else "***"

    @admin.display(description="Usage")
    def usage_display(self, obj):
        used = obj.daily_usage_count
        limit = obj.daily_usage_limit
        if used >= limit:
            return f"🔴 {used}/{limit} EXHAUSTED"
        if used >= limit * 0.8:
            return f"🟡 {used}/{limit}"
        return f"🟢 {used}/{limit}"

    @admin.action(description="Reset daily usage counters to 0")
    def reset_usage_counters(self, request, queryset):
        updated = queryset.update(daily_usage_count=0)
        self.message_user(request, f"Reset counters for {updated} key(s).")


# ── Video ──────────────────────────────────────────────────────────────

@admin.register(Video)
class VideoAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_display = [
        "video_id", "youtube_channel", "status_badge",
        "uploaded_to_profile", "retry_count", "created_at", "delete_button"
    ]
    list_filter = ["status", "youtube_channel__topic", "created_at"]
    search_fields = ["video_id", "youtube_channel__name"]
    autocomplete_fields = ["youtube_channel", "uploaded_to_profile"]
    readonly_fields = ["retry_count", "error_log"]
    actions = ["retry_distribution"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        emoji = {
            "pending": "⏳",
            "splitting": "✂️",
            "split": "📦",
            "processing": "🔄",
            "uploaded": "✅",
            "failed": "❌",
        }
        return f"{emoji.get(obj.status, '')} {obj.status}"

    @admin.action(description="Re-enqueue selected videos for distribution")
    def retry_distribution(self, request, queryset):
        from apps.core.tasks.distribute import distribute_video

        count = 0
        for video in queryset.filter(status__in=["pending", "failed", "split"]):
            video.status = Video.Status.PENDING
            video.retry_count = 0
            video.error_log = None
            video.save(update_fields=["status", "retry_count", "error_log"])
            distribute_video.delay(str(video.id))
            count += 1

        self.message_user(request, f"Re-enqueued {count} video(s) for distribution.")
