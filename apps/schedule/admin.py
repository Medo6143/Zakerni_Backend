from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.schedule.models import Course, Enrollment, Item, LectureSchedule


@admin.register(Course)
class CourseAdmin(ModelAdmin):
    list_display = ("code", "name", "moodle_course_id")
    search_fields = ("code", "name")
    readonly_fields = ("moodle_course_id", "created_at", "updated_at")


@admin.register(Enrollment)
class EnrollmentAdmin(ModelAdmin):
    list_display = ("user", "course", "group_name", "tutor_name", "is_active", "is_muted")
    list_filter = ("is_active", "is_muted")
    search_fields = ("user__moodle_username", "course__code")
    autocomplete_fields = ("course",)
    raw_id_fields = ("user",)


@admin.register(Item)
class ItemAdmin(ModelAdmin):
    list_display = (
        "title",
        "type",
        "source",
        "user",
        "course",
        "scheduled_at",
        "is_muted",
        "is_deleted",
    )
    list_filter = ("type", "source", "is_muted")
    search_fields = ("title", "user__moodle_username", "course__code")
    date_hierarchy = "scheduled_at"
    raw_id_fields = ("user", "course", "lecture_schedule")
    readonly_fields = ("external_id", "created_at", "updated_at", "deleted_at")

    @admin.display(boolean=True, description=_("deleted"))
    def is_deleted(self, obj: Item) -> bool:
        return obj.deleted_at is not None


@admin.register(LectureSchedule)
class LectureScheduleAdmin(ModelAdmin):
    list_display = ("title", "user", "course", "start_time", "starts_on", "ends_on")
    search_fields = ("title", "user__moodle_username")
    raw_id_fields = ("user", "course")
