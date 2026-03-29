"""
0001_initial.py — Initial schema migration for the subscriptions app.

Creates SubscriptionPlan, Subscription, and Payment tables.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        # ── SubscriptionPlan ────────────────────────────────────────────
        migrations.CreateModel(
            name="SubscriptionPlan",
            fields=[
                ("id",             models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name",           models.CharField(help_text="Display name, e.g. 'Basic', 'Premium', 'Supporter'.", max_length=100)),
                ("slug",           models.SlugField(help_text="URL-safe identifier. Auto-generated; do not change after creation.", unique=True)),
                ("description",    models.TextField(blank=True, help_text="Short plan description shown on the pricing page.")),
                ("price_usd",      models.DecimalField(decimal_places=2, help_text="Monthly or annual price in USD. Free plans use 0.00.", max_digits=6)),
                ("billing_period", models.CharField(choices=[("monthly", "Monthly"), ("annual", "Annual")], default="monthly", help_text="How often this plan is billed.", max_length=20)),
                ("features",       models.JSONField(blank=True, default=list, help_text="List of feature strings displayed on the pricing page.")),
                ("is_active",      models.BooleanField(db_index=True, default=True, help_text="Only active plans appear on the public pricing page.")),
                ("article_access", models.CharField(choices=[("free_only", "Free articles only"), ("premium", "Premium articles"), ("all", "All articles (Supporter)")], default="free_only", help_text="Which articles this plan unlocks for readers.", max_length=20)),
                ("created_at",     models.DateTimeField(auto_now_add=True)),
                ("updated_at",     models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Subscription Plan",
                "verbose_name_plural": "Subscription Plans",
                "ordering": ["price_usd"],
            },
        ),
        migrations.AddIndex(
            model_name="subscriptionplan",
            index=models.Index(fields=["is_active", "price_usd"], name="plan_active_price_idx"),
        ),

        # ── Subscription ────────────────────────────────────────────────
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id",                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reader",                models.ForeignKey(help_text="The reader who holds this subscription.", on_delete=django.db.models.deletion.CASCADE, related_name="subscriptions", to="accounts.readeraccount")),
                ("plan",                  models.ForeignKey(blank=True, help_text="The plan this subscription is on. SET_NULL on plan deletion.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="subscriptions", to="subscriptions.subscriptionplan")),
                ("status",                models.CharField(choices=[("active", "Active"), ("cancelled", "Cancelled"), ("expired", "Expired"), ("past_due", "Past Due"), ("trialing", "Trialing")], db_index=True, default="trialing", max_length=20)),
                ("started_at",            models.DateTimeField(default=django.utils.timezone.now, help_text="When this subscription was first created.")),
                ("current_period_start",  models.DateField(help_text="Start of the current billing period.")),
                ("current_period_end",    models.DateField(help_text="End of the current billing period. Paywall checks this date.")),
                ("cancelled_at",          models.DateTimeField(blank=True, help_text="When the reader requested cancellation. Null if not cancelled.", null=True)),
                ("cancel_at_period_end",  models.BooleanField(default=False, help_text="If True, the subscription remains active until current_period_end then transitions to CANCELLED.")),
                ("paynow_reference",      models.CharField(blank=True, help_text="Paynow transaction reference for the most recent payment.", max_length=100)),
                ("created_at",            models.DateTimeField(auto_now_add=True)),
                ("updated_at",            models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Subscription",
                "verbose_name_plural": "Subscriptions",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(fields=["reader", "status"], name="sub_reader_status_idx"),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(fields=["status", "current_period_end"], name="sub_status_period_end_idx"),
        ),

        # ── Payment ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id",                   models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subscription",         models.ForeignKey(help_text="The subscription this payment is for.", on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="subscriptions.subscription")),
                ("amount_usd",           models.DecimalField(decimal_places=2, help_text="Amount charged in USD.", max_digits=6)),
                ("currency",             models.CharField(default="USD", help_text="Currency code. Always USD for The Granite Post.", max_length=10)),
                ("payment_method",       models.CharField(choices=[("ecocash", "EcoCash"), ("onemoney", "OneMoney"), ("bank_card", "Bank Card"), ("bank_transfer", "Bank Transfer")], db_index=True, max_length=20)),
                ("status",               models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed"), ("refunded", "Refunded")], db_index=True, default="pending", max_length=20)),
                ("paynow_reference",     models.CharField(blank=True, help_text="Reference string returned by Paynow on payment initiation.", max_length=100)),
                ("paynow_poll_url",      models.CharField(blank=True, help_text="Paynow URL to poll to check payment completion status.", max_length=500)),
                ("paynow_redirect_url",  models.CharField(blank=True, help_text="Paynow URL to redirect the reader to for web/card payments.", max_length=500)),
                ("phone_number",         models.CharField(blank=True, help_text="Reader's mobile number for EcoCash or OneMoney payments.", max_length=20)),
                ("created_at",           models.DateTimeField(auto_now_add=True)),
                ("updated_at",           models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Payment",
                "verbose_name_plural": "Payments",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["status", "created_at"], name="payment_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["subscription", "status"], name="payment_sub_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["paynow_reference"], name="payment_paynow_ref_idx"),
        ),
    ]
