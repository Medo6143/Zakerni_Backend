from rest_framework.pagination import CursorPagination


class CursorSetPagination(CursorPagination):
    page_size = 20
    ordering = "-created_at"
    cursor_query_param = "cursor"
