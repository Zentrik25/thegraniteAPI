"""
0002_default_plans.py — Data migration to seed the three default subscription plans.

Creates:
  1. Free      — $0.00/month — FREE_ONLY access
  2. Premium   — $2.00/month — PREMIUM access (premium + free articles)
  3. Supporter — $5.00/month — ALL access + supporter badge
"""

from django.db import migrations


def create_default_plans(apps, schema_editor):
    """Insert the three default subscription plans."""
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")

    plans = [
        {
            "name":           "Free",
            "slug":           "free",
            "description":    "Access to all free articles. No payment required.",
            "price_usd":      "0.00",
            "billing_period": "monthly",
            "features": [
                "Access to all free articles",
                "Comment on articles",
                "Save bookmarks",
            ],
            "is_active":      True,
            "article_access": "free_only",
        },
        {
            "name":           "Premium",
            "slug":           "premium",
            "description":    "Full access to premium and free articles. $2.00 USD per month.",
            "price_usd":      "2.00",
            "billing_period": "monthly",
            "features": [
                "Access to all free articles",
                "Access to all premium articles",
                "Ad-free reading experience",
                "Comment on articles",
                "Save bookmarks",
                "Priority newsletter",
            ],
            "is_active":      True,
            "article_access": "premium",
        },
        {
            "name":           "Supporter",
            "slug":           "supporter",
            "description":    "Support independent journalism in Zimbabwe. $5.00 USD per month.",
            "price_usd":      "5.00",
            "billing_period": "monthly",
            "features": [
                "Access to all free articles",
                "Access to all premium articles",
                "Ad-free reading experience",
                "Supporter badge on your profile",
                "Early access to new features",
                "Comment on articles",
                "Save bookmarks",
                "Priority newsletter",
                "Monthly supporter digest",
            ],
            "is_active":      True,
            "article_access": "all",
        },
    ]

    for plan_data in plans:
        SubscriptionPlan.objects.get_or_create(
            slug=plan_data["slug"],
            defaults=plan_data,
        )


def delete_default_plans(apps, schema_editor):
    """Remove the three default plans (reverse migration)."""
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(slug__in=["free", "premium", "supporter"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_plans, delete_default_plans),
    ]
