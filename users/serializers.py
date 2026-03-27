from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import MANAGE_STAFF_ROLES, StaffRole, StaffUser


class UserPublicSerializer(serializers.ModelSerializer):
    byline        = serializers.ReadOnlyField()
    article_count = serializers.SerializerMethodField()

    class Meta:
        model  = StaffUser
        fields = (
            "id",
            "byline",
            "slug",
            "title",
            "bio",
            "avatar_url",
            "beat",
            "twitter_handle",
            "linkedin_url",
            "email_public",
            "article_count",
        )

    def get_article_count(self, obj) -> int:
        return obj.articles.filter(status="published").count()


class StaffUserSerializer(serializers.ModelSerializer):
    byline               = serializers.ReadOnlyField()
    can_publish          = serializers.ReadOnlyField()
    can_edit_any_article = serializers.ReadOnlyField()
    can_manage_staff     = serializers.ReadOnlyField()
    article_count        = serializers.SerializerMethodField()
    role_display         = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model  = StaffUser
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "byline",
            "display_name",
            "slug",
            "role",
            "role_display",
            "title",
            "bio",
            "avatar_url",
            "beat",
            "twitter_handle",
            "linkedin_url",
            "email_public",
            "is_active",
            "can_publish",
            "can_edit_any_article",
            "can_manage_staff",
            "article_count",
            "date_joined",
            "updated_at",
        )

    def get_article_count(self, obj) -> int:
        return obj.articles.count()


class StaffUserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        style={"input_type": "password"},
    )

    class Meta:
        model  = StaffUser
        fields = (
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "display_name",
            "role",
            "title",
            "bio",
            "avatar_url",
            "beat",
            "twitter_handle",
            "linkedin_url",
            "email_public",
            "is_active",
        )

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_role(self, value: str) -> str:
        request = self.context.get("request")
        if request and value == StaffRole.ADMIN:
            if not request.user.is_editorial_admin:
                raise serializers.ValidationError(
                    "Only Admins may assign the Admin role."
                )
        return value

    def create(self, validated_data: dict) -> StaffUser:
        password = validated_data.pop("password", None)
        user     = StaffUser(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance: StaffUser, validated_data: dict) -> StaffUser:
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class StaffUserMeSerializer(serializers.ModelSerializer):
    byline               = serializers.ReadOnlyField()
    can_publish          = serializers.ReadOnlyField()
    can_edit_any_article = serializers.ReadOnlyField()
    role_display         = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model  = StaffUser
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "byline",
            "display_name",
            "slug",
            "role",
            "role_display",
            "title",
            "bio",
            "avatar_url",
            "beat",
            "twitter_handle",
            "linkedin_url",
            "email_public",
            "can_publish",
            "can_edit_any_article",
            "date_joined",
            "updated_at",
        )
        read_only_fields = (
            "username",
            "role",
            "slug",
            "date_joined",
            "updated_at",
        )
