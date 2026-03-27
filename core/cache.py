import functools
import hashlib
import logging
import time
from typing import Any, Callable, Optional

from django.conf import settings
from django.core.cache import cache
from rest_framework.response import Response

logger = logging.getLogger("core.cache")

_DEFAULT_TTL = 300


def make_cache_key(key: str) -> str:
    prefix   = settings.CACHES.get("default", {}).get("KEY_PREFIX", "gp")
    full_key = f"{prefix}:{key}"
    if len(full_key) > 200:
        hashed   = hashlib.md5(full_key.encode()).hexdigest()
        full_key = f"{prefix}:h:{hashed}"
    return full_key


def invalidate_keys(*keys: str) -> None:
    full_keys = [make_cache_key(k) for k in keys]
    cache.delete_many(full_keys)
    logger.debug("Cache INVALIDATED: %s", full_keys)


def get_or_set_cache(
    key: str,
    compute: Callable[[], Any],
    ttl: Optional[int] = None,
    stampede_window: int = 5,
) -> Any:
    full_key = make_cache_key(key)
    lock_key = f"{full_key}:lock"

    value = cache.get(full_key)
    if value is not None:
        return value

    if cache.get(lock_key):
        time.sleep(0.05)
        value = cache.get(full_key)
        if value is not None:
            return value

    cache.set(lock_key, True, timeout=stampede_window)
    try:
        value         = compute()
        effective_ttl = ttl if ttl is not None else _DEFAULT_TTL
        cache.set(full_key, value, timeout=effective_ttl)
        logger.debug("Cache SET: %s (ttl=%ds)", full_key, effective_ttl)
    finally:
        cache.delete(lock_key)

    return value


def cache_response(
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None,
    cache_anonymous_only: bool = True,
    vary_on_user: bool = False,
):
    def decorator(view_func: Callable) -> Callable:
        @functools.wraps(view_func)
        def wrapper(view_instance, request, *args, **kwargs):
            if request.method != "GET":
                return view_func(view_instance, request, *args, **kwargs)

            if cache_anonymous_only and request.user.is_authenticated:
                return view_func(view_instance, request, *args, **kwargs)

            if key_func:
                raw_key = key_func(request, *args, **kwargs)
            else:
                raw_key = f"view:{request.get_full_path()}"

            if vary_on_user and request.user.is_authenticated:
                raw_key = f"{raw_key}:u{request.user.pk}"

            full_key = make_cache_key(raw_key)
            cached   = cache.get(full_key)

            if cached is not None:
                logger.debug("Cache HIT: %s", full_key)
                return Response(cached)

            logger.debug("Cache MISS: %s", full_key)
            response = view_func(view_instance, request, *args, **kwargs)

            if (
                hasattr(response, "data")
                and 200 <= getattr(response, "status_code", 200) < 300
            ):
                effective_ttl = (
                    ttl
                    or getattr(settings, "CACHE_TTL", {}).get("DEFAULT", _DEFAULT_TTL)
                )
                cache.set(full_key, response.data, timeout=effective_ttl)

            return response
        return wrapper
    return decorator


class CacheControlMixin:
    cache_max_age:                int  = 60
    cache_s_maxage:               int  = 300
    cache_stale_while_revalidate: int  = 60
    cache_stale_if_error:         int  = 86400
    cache_public:                 bool = True

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.method == "GET" and 200 <= response.status_code < 300:
            visibility = "public" if self.cache_public else "private"
            response["Cache-Control"] = (
                f"{visibility}, "
                f"max-age={self.cache_max_age}, "
                f"s-maxage={self.cache_s_maxage}, "
                f"stale-while-revalidate={self.cache_stale_while_revalidate}, "
                f"stale-if-error={self.cache_stale_if_error}"
            )
            response["Vary"] = "Accept-Encoding, Accept"
        return response


class NoCacheMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"]        = "no-cache"
        return response
