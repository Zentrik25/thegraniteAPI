from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand

from articles.models import Article, PublishStatus


class Command(BaseCommand):
    help = (
        "Rebuild the PostgreSQL full-text search index for all published articles. "
        "Run this once after installing the search app, and any time you suspect "
        "the search index is out of sync."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of articles to process per batch (default: 500).",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]

        total = Article.objects.filter(status=PublishStatus.PUBLISHED).count()
        self.stdout.write(
            f"Rebuilding search index for {total} published articles "
            f"(batch size: {batch_size})..."
        )

        updated = 0
        errors  = 0
        offset  = 0

        while True:
            batch = list(
                Article.objects
                .filter(status=PublishStatus.PUBLISHED)
                .values_list("pk", flat=True)
                .order_by("pk")[offset: offset + batch_size]
            )

            if not batch:
                break

            try:
                Article.objects.filter(pk__in=batch).update(
                    search_vector=(
                        SearchVector("title",   weight="A", config="english") +
                        SearchVector("excerpt", weight="B", config="english") +
                        SearchVector("body",    weight="C", config="english")
                    )
                )
                updated += len(batch)
                self.stdout.write(
                    f"  Updated {updated}/{total}...",
                    ending="\r",
                )
            except Exception as exc:
                errors += len(batch)
                self.stderr.write(
                    self.style.ERROR(
                        f"Error updating batch at offset {offset}: {exc}"
                    )
                )

            offset += batch_size

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Search index rebuilt: {updated} articles updated, {errors} errors."
            )
        )
