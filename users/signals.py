import logging

from django.contrib.auth.models import Group
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import StaffRole, StaffUser

logger = logging.getLogger("users.signals")

_ROLE_FLAGS = {
    StaffRole.CONTRIBUTOR:   ("Contributors",   False, False),
    StaffRole.AUTHOR:        ("Authors",        False, False),
    StaffRole.MODERATOR:     ("Moderators",    False, False), 
    StaffRole.EDITOR:        ("Editors",        True,  False),
    StaffRole.SENIOR_EDITOR: ("Senior Editors", True,  False),
    StaffRole.ADMIN:         ("Admins",         True,  True),
}


def _get_or_create_group(name: str) -> Group:
    group, _ = Group.objects.get_or_create(name=name)
    return group


@receiver(pre_save, sender=StaffUser)
def log_role_change(sender, instance, **kwargs) -> None:
    if instance.pk is None:
        return
    try:
        previous = sender.objects.only("role").get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    if previous.role != instance.role:
        logger.info(
            "StaffUser pk=%s '%s': role %s → %s.",
            instance.pk,
            instance.username,
            previous.role,
            instance.role,
        )


@receiver(post_save, sender=StaffUser)
def sync_role_to_django_permissions(sender, instance, created, **kwargs) -> None:
    role                                   = instance.role
    group_name, should_be_staff, should_be_superuser = _ROLE_FLAGS.get(
        role, ("Contributors", False, False)
    )

    needs_update = (
        instance.is_staff != should_be_staff
        or instance.is_superuser != should_be_superuser
    )
    if needs_update:
        sender.objects.filter(pk=instance.pk).update(
            is_staff=should_be_staff,
            is_superuser=should_be_superuser,
        )
        # Keep the in-memory instance in sync so callers don't need refresh_from_db().
        instance.is_staff     = should_be_staff
        instance.is_superuser = should_be_superuser

    all_role_groups = [
        _get_or_create_group(name)
        for name, _, _ in _ROLE_FLAGS.values()
    ]
    target_group = _get_or_create_group(group_name)
    instance.groups.remove(*all_role_groups)
    instance.groups.add(target_group)

    if created:
        logger.info(
            "StaffUser pk=%s '%s' created with role '%s' → group '%s'.",
            instance.pk,
            instance.username,
            role,
            group_name,
        )
