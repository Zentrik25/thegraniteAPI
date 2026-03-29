from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Delete audit log entries older than the specified number of days. "
        "Default: 730 days (2 years). "
        "Run monthly via cron: python manage.py prune_audit_log"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=730,
            help="Delete entries older than this many days (default: 730).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many records would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        from audit.models import AuditLog

        days    = options["days"]
        dry_run = options["dry_run"]
        cutoff  = timezone.now() - timedelta(days=days)

        qs    = AuditLog.objects.filter(created_at__lt=cutoff)
        count = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — would delete {count} audit log "
                    f"entries older than {days} days (before {cutoff:%Y-%m-%d})."
                )
            )
            return

        if count == 0:
            self.stdout.write("No audit log entries to prune.")
            return

        qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {count} audit log entries older than "
                f"{days} days (before {cutoff:%Y-%m-%d})."
            )
        )