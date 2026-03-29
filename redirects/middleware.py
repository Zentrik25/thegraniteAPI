import logging

from django.http import HttpResponsePermanentRedirect

logger = logging.getLogger("redirects.middleware")

REDIRECT_CACHE_TTL = 600
NO_REDIRECT        = "__no_redirect__"


class RedirectMiddleware:
    """
    Intercepts 404 responses and checks the redirects table.
    If a matching active redirect is found returns a 301.

    Only runs on 404 responses — zero overhead on normal requests.
    Caches both hits and misses to avoid repeated DB queries.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code != 404:
            return response

        return self._check_redirect(request, response)

    def _check_redirect(self, request, original_response):
        path = request.path_info

        if not path.endswith("/"):
            normalised = f"{path}/"
        else:
            normalised = path

        cached = self._get_cached(normalised)

        if cached == NO_REDIRECT:
            return original_response

        if cached is not None:
            logger.debug("Redirect cache hit: %s → %s", normalised, cached)
            self._increment_hits(normalised)
            return HttpResponsePermanentRedirect(cached)

        new_path = self._lookup(normalised)

        if new_path:
            self._set_cache(normalised, new_path)
            self._increment_hits(normalised)
            logger.info("Redirect: %s → %s", normalised, new_path)
            return HttpResponsePermanentRedirect(new_path)

        self._set_cache(normalised, NO_REDIRECT)
        return original_response

    def _lookup(self, path: str):
        try:
            from .models import Redirect
            redirect = Redirect.objects.get(old_path=path, is_active=True)
            return redirect.new_path
        except Redirect.DoesNotExist:
            return None
        except Exception as exc:
            logger.error("Redirect lookup error for %s: %s", path, exc)
            return None

    def _get_cached(self, path: str):
        try:
            from django.core.cache import cache
            from core.cache import make_cache_key
            return cache.get(make_cache_key(f"redirect:{path}"))
        except Exception:
            return None

    def _set_cache(self, path: str, value: str) -> None:
        try:
            from django.core.cache import cache
            from core.cache import make_cache_key
            cache.set(
                make_cache_key(f"redirect:{path}"),
                value,
                REDIRECT_CACHE_TTL,
            )
        except Exception:
            pass

    def _increment_hits(self, path: str) -> None:
        try:
            from .tasks import increment_redirect_hits
            increment_redirect_hits.apply_async(args=[path], queue="slow")
        except Exception:
            try:
                from django.db.models import F
                from .models import Redirect
                Redirect.objects.filter(old_path=path).update(
                    hits=F("hits") + 1
                )
            except Exception:
                pass