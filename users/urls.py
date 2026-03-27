from django.urls import path

from .views import (
    UserDetailView,
    UserListView,
    ChangePasswordView,
    MeView,
    StaffDetailView,
    StaffListCreateView,
)

app_name = "users"

urlpatterns = [
    # Public — no auth required
    path("users/",             UserListView.as_view(),   name="user-list"),
    path("users/<slug:slug>/", UserDetailView.as_view(), name="user-detail"),

    # Internal staff management — Senior Editor / Admin only
    path("staff/",          StaffListCreateView.as_view(), name="staff-list"),
    path("staff/<int:pk>/", StaffDetailView.as_view(),     name="staff-detail"),

    # Current user's own profile — any authenticated staff
    path("auth/me/",              MeView.as_view(),             name="me"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="change-password"),
]
