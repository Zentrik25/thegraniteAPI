import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination

from .models import StaffUser
from .permissions import CanManageStaff, IsEditorOrAbove, IsStaffUser
from .serializers import (
    UserPublicSerializer,
    StaffUserMeSerializer,
    StaffUserSerializer,
    StaffUserWriteSerializer,
)

logger = logging.getLogger("users.views")


class UserListView(generics.ListAPIView):
    serializer_class = UserPublicSerializer

    def get_queryset(self):
        return (
            StaffUser.objects
            .filter(is_active=True, articles__status="published")
            .distinct()
            .order_by("last_name", "first_name")
        )


class UserDetailView(APIView):
    def get(self, request, slug):
        user = get_object_or_404(StaffUser, slug=slug, is_active=True)

        from articles.serializers import ArticleListSerializer

        articles = (
            user.articles
            .filter(status="published")
            .select_related("category")
            .prefetch_related("tags")
            .order_by("-published_at")
        )

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(articles, request, view=self)
        return Response({
            "user":         UserPublicSerializer(user, context={"request": request}).data,
            "count":        paginator.page.paginator.count,
            "total_pages":  paginator.page.paginator.num_pages,
            "current_page": paginator.page.number,
            "page_size":    paginator.get_page_size(request),
            "next":         paginator.get_next_link(),
            "previous":     paginator.get_previous_link(),
            "articles":     ArticleListSerializer(page, many=True, context={"request": request}).data,
        })


class StaffListCreateView(generics.ListCreateAPIView):

    def get_queryset(self):
        return StaffUser.objects.all().order_by("role", "last_name")

    def get_serializer_class(self):
        return StaffUserWriteSerializer if self.request.method == "POST" else StaffUserSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), CanManageStaff()]
        return [IsAuthenticated(), IsEditorOrAbove()]

    def perform_create(self, serializer):
        user = serializer.save()
        logger.info(
            "Staff user created: pk=%s username=%s role=%s by pk=%s.",
            user.pk,
            user.username,
            user.role,
            self.request.user.pk,
        )


class StaffDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StaffUser.objects.all()

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return StaffUserWriteSerializer
        return StaffUserSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [IsAuthenticated(), CanManageStaff()]
        return [IsAuthenticated(), IsEditorOrAbove()]

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user == request.user:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        logger.info(
            "Staff user deactivated: pk=%s username=%s by pk=%s.",
            user.pk,
            user.username,
            request.user.pk,
        )
        return Response(
            {"detail": f"{user.byline} has been deactivated."},
            status=status.HTTP_200_OK,
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class   = StaffUserMeSerializer
    permission_classes = [IsAuthenticated, IsStaffUser]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated, IsStaffUser]

    def post(self, request):
        user             = request.user
        current_password = request.data.get("current_password", "")
        new_password     = request.data.get("new_password", "")

        if not current_password or not new_password:
            return Response(
                {"detail": "Both current_password and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(new_password, user)
        except ValidationError as exc:
            return Response(
                {"detail": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        logger.info("StaffUser pk=%s changed password.", user.pk)
        return Response({"detail": "Password updated successfully."})
