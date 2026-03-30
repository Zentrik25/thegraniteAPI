"""
Management command: check_subscription_constraints

Preflight validation for migration 0004.

Migration 0004 adds two partial unique constraints:

  1. unique_effective_subscription_per_reader
     One ACTIVE or TRIALING subscription per reader.
     Condition: status IN ('active', 'trialing')

  2. unique_payment_paynow_reference
     No two payments share the same non-empty Paynow reference.
     Condition: paynow_reference != ''

If either constraint is already violated in the live database, running
``python manage.py migrate`` will raise IntegrityError and leave the
schema in a partially-applied state.

This command detects violations WITHOUT modifying any data.
Exit code 0 = safe to migrate. Exit code 1 = violations found, do not migrate.

Usage
-----
  # Check only (safe — read-only)
  python manage.py check_subscription_constraints

  # Non-zero exit on violations — use in CI or deploy scripts
  python manage.py check_subscription_constraints && python manage.py migrate
"""

import sys

from django.core.management.base import BaseCommand
from django.db.models import Count


class Command(BaseCommand):
    help = (
        "Preflight check for migration 0004 constraints. "
        "Reports violations without modifying data. "
        "Exits with code 1 if violations are found."
    )

    def handle(self, *args, **options):
        violations = 0
        violations += self._check_duplicate_active_subscriptions()
        violations += self._check_duplicate_paynow_references()

        if violations == 0:
            self.stdout.write(self.style.SUCCESS(
                "\nAll checks passed. Safe to run: python manage.py migrate"
            ))
            sys.exit(0)
        else:
            self.stderr.write(self.style.ERROR(
                f"\n{violations} violation(s) found. "
                "Resolve them before running python manage.py migrate. "
                "See remediation guidance below each violation."
            ))
            sys.exit(1)

    # ------------------------------------------------------------------
    # Check 1 — duplicate ACTIVE/TRIALING subscriptions per reader
    # ------------------------------------------------------------------

    def _check_duplicate_active_subscriptions(self) -> int:
        """
        Find readers who have more than one ACTIVE or TRIALING subscription.
        The migration constraint allows at most one per reader.
        """
        from subscriptions.models import Subscription, SubscriptionStatus

        self.stdout.write("\n[1/2] Checking for duplicate ACTIVE/TRIALING subscriptions...")

        duplicates = (
            Subscription.objects
            .filter(status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING])
            .values("reader_id")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .order_by("-cnt")
        )

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("    OK — no duplicates found."))
            return 0

        self.stderr.write(self.style.ERROR(
            f"    FAIL — {len(duplicates)} reader(s) have multiple ACTIVE/TRIALING subscriptions:"
        ))
        self.stderr.write("")

        for row in duplicates:
            reader_id = row["reader_id"]
            count     = row["cnt"]
            subs = (
                Subscription.objects
                .filter(
                    reader_id=reader_id,
                    status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING],
                )
                .order_by("-created_at")
                .values("id", "status", "plan_id", "current_period_end", "created_at")
            )
            self.stderr.write(
                f"    Reader {reader_id} — {count} conflicting subscriptions:"
            )
            for sub in subs:
                self.stderr.write(
                    f"      id={sub['id']}  status={sub['status']}"
                    f"  period_end={sub['current_period_end']}"
                    f"  created={sub['created_at'].date()}"
                )
            self.stderr.write("")

        self.stderr.write(self.style.WARNING("    Remediation (manual — review before applying):"))
        self.stderr.write(
            "      Keep the most recent ACTIVE subscription for each reader.\n"
            "      Mark older duplicates as EXPIRED:\n\n"
            "        UPDATE subscriptions_subscription\n"
            "        SET status = 'expired', updated_at = NOW()\n"
            "        WHERE id = '<older_subscription_id>';\n\n"
            "      Verify with:\n"
            "        SELECT reader_id, COUNT(*) FROM subscriptions_subscription\n"
            "        WHERE status IN ('active', 'trialing')\n"
            "        GROUP BY reader_id HAVING COUNT(*) > 1;\n"
        )
        return len(duplicates)

    # ------------------------------------------------------------------
    # Check 2 — duplicate non-empty Paynow references in payments
    # ------------------------------------------------------------------

    def _check_duplicate_paynow_references(self) -> int:
        """
        Find non-empty paynow_reference values that appear on more than
        one Payment row. The migration constraint requires uniqueness.
        """
        from subscriptions.models import Payment

        self.stdout.write("[2/2] Checking for duplicate Paynow references in payments...")

        duplicates = (
            Payment.objects
            .exclude(paynow_reference="")
            .values("paynow_reference")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .order_by("-cnt")
        )

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("    OK — no duplicates found."))
            return 0

        self.stderr.write(self.style.ERROR(
            f"    FAIL — {len(duplicates)} Paynow reference(s) appear on multiple payments:"
        ))
        self.stderr.write("")

        for row in duplicates:
            ref   = row["paynow_reference"]
            count = row["cnt"]
            payments = (
                Payment.objects
                .filter(paynow_reference=ref)
                .order_by("created_at")
                .values("id", "status", "amount_usd", "created_at", "subscription_id")
            )
            self.stderr.write(f"    Reference '{ref}' — {count} payments:")
            for p in payments:
                self.stderr.write(
                    f"      id={p['id']}  status={p['status']}"
                    f"  amount=${p['amount_usd']}"
                    f"  sub={p['subscription_id']}"
                    f"  created={p['created_at'].date()}"
                )
            self.stderr.write("")

        self.stderr.write(self.style.WARNING("    Remediation (manual — review before applying):"))
        self.stderr.write(
            "      Duplicate references typically occur from retry storms or double-submits.\n"
            "      For each duplicate set, identify the legitimate COMPLETED payment\n"
            "      and clear the reference on the spurious duplicate(s):\n\n"
            "        UPDATE subscriptions_payment\n"
            "        SET paynow_reference = '', updated_at = NOW()\n"
            "        WHERE id = '<spurious_payment_id>';\n\n"
            "      Verify with:\n"
            "        SELECT paynow_reference, COUNT(*) FROM subscriptions_payment\n"
            "        WHERE paynow_reference != ''\n"
            "        GROUP BY paynow_reference HAVING COUNT(*) > 1;\n"
        )
        return len(duplicates)
