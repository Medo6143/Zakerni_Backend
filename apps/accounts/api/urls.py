from django.urls import path

from apps.accounts.api.views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
    SignInView,
)

urlpatterns = [
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/signin", SignInView.as_view(), name="auth-signin"),
    path("auth/change-password", ChangePasswordView.as_view(), name="auth-change-password"),
    path("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="me"),
]
