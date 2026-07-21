"""Django Admin configuration for all core models."""
from django.contrib import admin

from apps.core.models import Topic, VPS, YouTubeChannel, TikTokProfile, Video, GeminiAPIKey, SystemConfig
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
    list_per_page = 20
    list_display = ["name", "slug", "bypass_cooldown", "channel_count", "profile_count", "created_at", "delete_button"]
    list_editable = ["bypass_cooldown"]
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
    list_per_page = 20
    list_display = ["name", "channel_id", "topic", "is_active", "video_count", "created_at", "delete_button"]
    list_filter = ["is_active", "topic"]
    search_fields = ["name", "channel_id"]
    list_editable = ["topic", "is_active"]
    autocomplete_fields = ["topic"]
    actions = ["trigger_manual_scan"]

    @admin.display(description="Videos")
    def video_count(self, obj):
        return obj.videos.count()

    @admin.action(description="📥 Quét và Phân phối Video chọn lọc")
    def trigger_manual_scan(self, request, queryset):
        from django.http import HttpResponseRedirect
        selected_ids = list(queryset.values_list("id", flat=True))
        request.session["selected_channel_ids"] = [str(x) for x in selected_ids]
        return HttpResponseRedirect("scan-config/")

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path("scan-config/", self.admin_site.admin_view(self.scan_config_view), name="youtubechannel_scan_config"),
        ]
        return custom_urls + urls

    def scan_config_view(self, request):
        from django.http import HttpResponseRedirect
        from django.shortcuts import render
        from django.contrib import messages
        from apps.core.tasks.fetch_videos import fetch_and_process_channel_videos_manual

        selected_ids = request.session.get("selected_channel_ids", [])
        if not selected_ids:
            self.message_user(request, "Vui lòng chọn ít nhất một kênh YouTube.", level=messages.WARNING)
            return HttpResponseRedirect("../")

        channels = YouTubeChannel.objects.filter(id__in=selected_ids)

        # Tính toán dung lượng trống cho từng kênh dựa trên Topic và các Profile tương ứng
        channels_with_capacity = []
        max_remaining_capacity = 0
        
        for channel in channels:
            remaining = 0
            if channel.topic:
                profiles = channel.topic.tiktok_profiles.filter(is_active=True, vps__is_active=True)
                remaining = sum(max(0, p.daily_video_limit - p.videos_today) for p in profiles)
            
            channels_with_capacity.append({
                "instance": channel,
                "remaining_capacity": remaining,
                "topic_name": channel.topic.name if channel.topic else "Chưa gán chủ đề",
            })
            if remaining > max_remaining_capacity:
                max_remaining_capacity = remaining

        # Giá trị gợi ý mặc định là dung lượng trống lớn nhất tìm thấy (hoặc tối thiểu là 5 nếu tất cả bằng 0)
        default_max_videos = max_remaining_capacity if max_remaining_capacity > 0 else 5

        if request.method == "POST":
            max_videos = int(request.POST.get("max_videos", 5))
            min_views = int(request.POST.get("min_views", 0))

            for channel in channels:
                fetch_and_process_channel_videos_manual.delay(
                    str(channel.id),
                    max_videos,
                    min_views
                )

            self.message_user(
                request,
                f"Đã kích hoạt quét thành công cho {channels.count()} kênh. Tiến trình đang chạy ngầm.",
                level=messages.SUCCESS
            )
            if "selected_channel_ids" in request.session:
                del request.session["selected_channel_ids"]
            return HttpResponseRedirect("../")

        context = {
            **self.admin_site.each_context(request),
            "title": "Cấu hình quét và lọc video YouTube",
            "channels_with_capacity": channels_with_capacity,
            "default_max_videos": default_max_videos,
            "opts": self.model._meta,
        }
        return render(request, "admin/core/youtubechannel/scan_config.html", context)


# ── VPS ────────────────────────────────────────────────────────────────

@admin.register(VPS)
class VPSAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_per_page = 20
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
    list_per_page = 20
    list_display = [
        "profile_name", "topic", "vps", "is_active", "is_beta",
        "videos_today", "daily_video_limit", "capacity_status",
        "last_upload_at", "created_at", "delete_button"
    ]
    list_filter = ["is_active", "is_beta", "topic", "vps"]
    search_fields = ["profile_name"]
    list_editable = ["is_active", "is_beta", "daily_video_limit"]
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
    list_per_page = 20
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
    list_per_page = 20
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


# ── System Config ────────────────────────────────────────────────────────

@admin.register(SystemConfig)
class SystemConfigAdmin(DeleteActionMixin, admin.ModelAdmin):
    list_per_page = 20
    list_display = ["key", "value", "created_at", "delete_button"]
    search_fields = ["key"]
    list_editable = ["value"]
