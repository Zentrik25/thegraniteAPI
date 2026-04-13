"""
nextjs_revalidate.py — Trigger Next.js on-demand ISR revalidation.

Requires in .env / Django settings:
    NEXTJS_URL               — https://www.thegranite.co.zw  (defaults to FRONTEND_URL)
    NEXTJS_REVALIDATE_SECRET — matches REVALIDATE_SECRET in the Next.js env
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger("core.nextjs_revalidate")


def revalidate_article(
    slug: str,
    section_slug: str | None = None,
    category_slug: str | None = None,
) -> bool:
    nextjs_url = getattr(settings, "NEXTJS_URL", "").rstrip("/")
    secret = getattr(settings, "NEXTJS_REVALIDATE_SECRET", "")
    if not nextjs_url:
        logger.debug("NEXTJS_URL not set — skipping revalidation.")
        return False

    payload: dict = {
        "secret": secret,
        "article_slug": slug,
        "paths": ["/feed.xml", "/news-sitemap.xml", "/sitemap.xml"],
    }
    if section_slug:
        payload["section_slug"] = section_slug
    if category_slug:
        payload["category_slug"] = category_slug

    try:
        response = requests.post(
            f"{nextjs_url}/api/revalidate",
            json=payload,
            timeout=5,
        )
        if response.status_code == 200:
            logger.info("Next.js revalidated for slug=%s", slug)
            return True
        logger.warning(
            "Next.js revalidate HTTP %d for slug=%s: %s",
            response.status_code,
            slug,
            response.text[:200],
        )
        return False
    except Exception as exc:
        logger.error("Next.js revalidate error for slug=%s: %s", slug, exc)
        return False
