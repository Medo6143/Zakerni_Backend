from django.urls import path

from apps.schedule.api.views import (
    CourseDetailView,
    CourseListView,
    ItemDetailView,
    ItemListCreateView,
    ItemMuteView,
    ItemStatusNoteView,
    LectureDetailView,
    LectureListCreateView,
)

urlpatterns = [
    path("items", ItemListCreateView.as_view(), name="items"),
    path("items/<uuid:item_id>", ItemDetailView.as_view(), name="item-detail"),
    path("items/<uuid:item_id>/mute", ItemMuteView.as_view(), name="item-mute"),
    path("items/<uuid:item_id>/status", ItemStatusNoteView.as_view(), name="item-status"),
    path("lectures", LectureListCreateView.as_view(), name="lectures"),
    path("lectures/<uuid:schedule_id>", LectureDetailView.as_view(), name="lecture-detail"),
    path("courses", CourseListView.as_view(), name="courses"),
    path("courses/<uuid:course_id>", CourseDetailView.as_view(), name="course-detail"),
]
