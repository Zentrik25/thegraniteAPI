from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from core.throttling import StrictAnonThrottle


class GraniteTokenObtainPairSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"]         = user.role
        token["display_name"] = user.byline
        token["can_publish"]  = user.can_publish
        return token

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        user = self.user

        data["user"] = {
            "id":                   user.pk,
            "username":             user.username,
            "display_name":         user.byline,
            "slug":                 user.slug,
            "role":                 user.role,
            "role_display":         user.get_role_display(),
            "avatar_url":           user.avatar_url,
            "title":                user.title,
            "can_publish":          user.can_publish,
            "can_edit_any_article": user.can_edit_any_article,
            "can_manage_staff":     user.can_manage_staff,
            "is_editorial_admin":   user.is_editorial_admin,
        }

        return data


class GraniteTokenObtainPairView(TokenObtainPairView):
    serializer_class = GraniteTokenObtainPairSerializer
    throttle_classes = [StrictAnonThrottle]
