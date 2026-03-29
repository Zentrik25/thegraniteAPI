"""
0007_add_is_premium_to_article.py — Add is_premium paywall flag to Article.

All existing articles default to is_premium=False (free) so no content
is accidentally paywalled after this migration runs.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("articles", "0006_add_section_fk_to_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="is_premium",
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text=(
                    "Tick to gate this article behind a paid subscription. "
                    "Free readers will see a 402 Payment Required response."
                ),
            ),
        ),
    ]
