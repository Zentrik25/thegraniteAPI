# The Granite Post — Backend Audit Report
**Date:** 2026-03-29
**Auditor:** Senior Backend Engineer / Systems Architect
**Scope:** Full Django REST Framework backend — authentication, articles, subscriptions, payments, paywall, caching, infrastructure
**Verdict:** ⚠️ NOT production-ready in current state. See critical issues.

---

## 🔴 CRITICAL ISSUES (must fix before go-live)

---

### CRITICAL-01 — Race condition: subscription can be double-activated

**Location:** `subscriptions/views.py:450-457` (PaynowPollView) + `subscriptions/tasks.py:169-188` (process_paynow_callback)

**Problem:**
Two independent code paths can activate the same subscription simultaneously with zero coordination:
- The reader's browser polls `GET /paynow-poll/<id>/` → calls `_activate_subscription(payment)`
- Paynow fires the result URL → enqueues `process_paynow_callback` → same activation

If both run at the same time (highly likely — Paynow fires the callback while the reader is polling), both see `payment.status != COMPLETED`, both call activate, both write `payment.status = COMPLETED` and `subscription.status = ACTIVE`. No `select_for_update()`, no atomicity, no idempotency guard anywhere.

In practice this produces double `subscription.save()` calls, corrupted `updated_at`, and — if the subscription had any billing logic added later — double-charges.

**Fix:**
```python
# In both _activate_subscription() and process_paynow_callback:
from django.db import transaction

with transaction.atomic():
    payment = Payment.objects.select_for_update().get(id=payment.id)
    if payment.status == PaymentStatus.COMPLETED:
        return  # Already done — idempotency guard
    payment.status = PaymentStatus.COMPLETED
    payment.save(update_fields=["status", "updated_at"])
    payment.subscription.status = SubscriptionStatus.ACTIVE
    payment.subscription.save(update_fields=["status", "paynow_reference", "updated_at"])
```

---

### CRITICAL-02 — `_activate_subscription` is not atomic

**Location:** `subscriptions/views.py:570-589`

**Problem:**
```python
payment.status = PaymentStatus.COMPLETED
payment.save(update_fields=["status", "updated_at"])   # write 1

subscription.status = SubscriptionStatus.ACTIVE
subscription.save(update_fields=["status", ...])        # write 2
```

If the process crashes, is killed, or the DB connection drops between write 1 and write 2, the reader has paid (payment = COMPLETED) but has no access (subscription = TRIALING). You have taken their money and given them nothing. Same pattern exists in `tasks.py:170-176`.

**Fix:** Wrap both writes in `transaction.atomic()` with `select_for_update()` as shown in CRITICAL-01.

---

### CRITICAL-03 — Paid amount is never verified against plan price

**Location:** `subscriptions/tasks.py:169` + `subscriptions/views.py:450`

**Problem:**
```python
if result["paid"]:   # only checks paid=True
    # activates subscription without checking result["amount"]
```

The `check_payment_status()` method returns `result["amount"]` from Paynow's poll response. This is never compared against `payment.amount_usd`. A sophisticated attacker could:
1. Initiate a legitimate Premium subscription request ($2.00)
2. Pay $0.01 through a manipulated Paynow response
3. Get full premium access because the code only checks `paid == True`

This is a direct financial attack vector.

**Fix:**
```python
if result["paid"]:
    paid_amount = Decimal(str(result["amount"]))
    if paid_amount < payment.amount_usd:
        logger.error(
            "Amount mismatch: expected=%.2f paid=%.2f payment=%s",
            payment.amount_usd, paid_amount, payment.id,
        )
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status", "updated_at"])
        return
```

---

### CRITICAL-04 — OneMoney payments are sent to Paynow as EcoCash

**Location:** `subscriptions/paynow_client.py:86`

**Problem:**
```python
def initiate_mobile_payment(self, amount_usd, phone, email, reference):
    # ...
    response = self._paynow.send_mobile(payment, phone, "ecocash")  # HARDCODED
```

The method is called for both EcoCash and OneMoney (views.py:203-209), but the Paynow provider is hardcoded to `"ecocash"`. OneMoney payments will be routed to EcoCash and will fail or — worse — charge the wrong wallet. This is a direct payment processing bug.

**Fix:** Pass the provider as a parameter:
```python
def initiate_mobile_payment(self, amount_usd, phone, email, reference, provider="ecocash"):
    response = self._paynow.send_mobile(payment, phone, provider)
```
And in `views.py`:
```python
provider = "onemoney" if payment_method == PaymentMethod.ONEMONEY else "ecocash"
result = paynow.initiate_mobile_payment(..., provider=provider)
```

---

### CRITICAL-05 — No duplicate subscription guard

**Location:** `subscriptions/views.py:191-198`

**Problem:**
`SubscribeView.post()` creates a new `Subscription` record without checking whether the reader already has an ACTIVE or TRIALING subscription. A reader can click Subscribe 3 times rapidly and create 3 TRIALING subscriptions and 3 Paynow payment requests for the same plan. There is no DB-level constraint preventing multiple active subscriptions per reader.

This means:
- A reader can theoretically be charged multiple times
- The `my-subscription/` endpoint returns `.first()` which could return any of them
- Cache invalidation logic only tracks one subscription

**Fix:**
```python
# In SubscribeView.post(), before creating the subscription:
existing = Subscription.objects.filter(
    reader=reader,
    status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING],
).first()
if existing:
    return Response(
        {"detail": "You already have an active subscription.", "subscription_id": str(existing.id)},
        status=status.HTTP_409_CONFLICT,
    )
```
Also add a DB-level partial unique index:
```python
# In Subscription.Meta.constraints:
models.UniqueConstraint(
    fields=["reader"],
    condition=Q(status__in=["active", "trialing"]),
    name="subscription_unique_active_per_reader",
)
```

---

### CRITICAL-06 — `BurstRateThrottle` skips ALL GET requests

**Location:** `core/throttling.py:81`

**Problem:**
```python
def allow_request(self, request, view) -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True   # ← No rate limiting for GET
```

This means `PaynowPollView` (GET) has zero burst protection. An attacker or a buggy frontend can hammer `GET /paynow-poll/<id>/` thousands of times per second. Each call hits the Paynow API externally. This can:
- Exhaust your Paynow API quota
- Create a Paynow-reported DDoS from your IP
- Degrade response times for all users

The poll endpoint is particularly dangerous because it makes an outbound HTTP call to Paynow on every request.

**Fix:** Apply `StrictAnonThrottle` explicitly on `PaynowPollView`, and remove the blanket GET exemption from `BurstRateThrottle` (or make it configurable per-view).

---

### CRITICAL-07 — `check_expired_subscriptions` double-query logic is broken

**Location:** `subscriptions/tasks.py:34-64`

**Problem:**
The task runs two queries. Query 1 (lines 34-44) marks ALL `ACTIVE` subscriptions with expired periods as `EXPIRED`. Query 2 (lines 51-64) then tries to find `ACTIVE` subscriptions with `cancel_at_period_end=True` and expired periods and mark them `CANCELLED`.

Query 2 will **always return zero rows** because every subscription matching its filter conditions was already set to `EXPIRED` by Query 1. Those subscriptions are no longer `ACTIVE` by the time Query 2 runs. The cancel finalisation logic is dead code that has never worked.

Additionally: `expired_qs.count()` then `expired_qs.update()` is a TOCTOU pattern — the count and update are not atomic. Use the return value of `update()` instead.

**Fix:**
```python
from django.db import transaction

with transaction.atomic():
    # Handle cancel_at_period_end FIRST, before the general expiry sweep
    cancel_count = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        current_period_end__lt=today,
    ).update(status=SubscriptionStatus.CANCELLED)

    # Then expire the rest
    expired_count = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        current_period_end__lt=today,
    ).update(status=SubscriptionStatus.EXPIRED)
```

---

### CRITICAL-08 — Subscription cache never invalidated after bulk expiry

**Location:** `subscriptions/tasks.py:66-68`

**Problem:**
```python
# Invalidate affected reader caches — broad flush for now
# (production would target specific reader IDs)
logger.info("[check_expired_subscriptions] Task complete.")
```

The comment acknowledges this is not implemented. When `check_expired_subscriptions` bulk-expires subscriptions, **the per-reader cache keys are never cleared**. A reader whose subscription just expired will continue to bypass the paywall for up to 5 more minutes (the `_CACHE_TTL`). In extreme cases — if the reader's cache was refreshed just before midnight — they get 5 minutes of free premium access after their subscription ended.

**Fix:**
```python
# Collect reader IDs before updating
reader_ids = list(Subscription.objects.filter(
    status=SubscriptionStatus.ACTIVE,
    current_period_end__lt=today,
).values_list("reader_id", flat=True))

# Update
Subscription.objects.filter(reader_id__in=reader_ids, ...).update(...)

# Invalidate caches
keys = [f"subscriptions:reader:{rid}:status" for rid in reader_ids]
cache.delete_many(keys)
```

---

### CRITICAL-09 — `SECRET_KEY` has no production enforcement

**Location:** `config/settings.py:27-30`

**Problem:**
```python
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-change-me-in-production",
)
```

There is no check that this has been overridden in production. If deployed without `SECRET_KEY` in environment (easy to forget), all JWT tokens, session cookies, and CSRF tokens are signed with a public, well-known key. Anyone can forge staff JWTs and bypass the paywall or access admin.

**Fix:**
```python
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is required in production."
        )
    SECRET_KEY = "django-insecure-dev-only-key-do-not-use-in-production"
```

---

## 🟠 HIGH PRIORITY IMPROVEMENTS

---

### HIGH-01 — Paywall middleware queries DB for every article request, including free ones

**Location:** `subscriptions/middleware.py:65-72`

**Problem:**
```python
article = Article.objects.only("slug", "is_premium", "status").get(
    slug=slug, status=PublishStatus.PUBLISHED,
)
```

This query runs on **every** `GET /api/v1/articles/<slug>/` request — free or premium. A news site has 99% free articles. The middleware is adding a DB lookup to every single article read just to check `is_premium`. At 10k readers/day this is a meaningless overhead. At 100k it becomes a problem.

**Fix:** Cache the `(slug → is_premium)` lookup:
```python
cache_key = f"article:is_premium:{slug}"
is_premium = cache.get(cache_key)
if is_premium is None:
    try:
        article = Article.objects.only("slug", "is_premium", "status").get(
            slug=slug, status=PublishStatus.PUBLISHED,
        )
        is_premium = article.is_premium
    except Article.DoesNotExist:
        return self.get_response(request)
    cache.set(cache_key, is_premium, 600)  # 10 minutes

if not is_premium:
    return self.get_response(request)
```
Invalidate this key in `purge_cloudflare_on_publish`.

---

### HIGH-02 — `_paywall_response` hits the DB on every 402

**Location:** `subscriptions/middleware.py:107-114`

**Problem:**
Every unauthenticated request to a premium article triggers:
```python
SubscriptionPlan.objects.filter(is_active=True, ...).values(...)
```
This query runs for **every** 402 response. Plans are nearly static data. Cache this aggressively.

**Fix:** Cache plan list in `_paywall_response` with a 1-hour TTL and invalidate on plan changes.

---

### HIGH-03 — Revenue report is O(N) queries where N = number of plans

**Location:** `subscriptions/views.py:538-551`

**Problem:**
```python
for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("price_usd"):
    active_count = Subscription.objects.filter(
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        ...
    ).count()   # ← One DB query PER PLAN
```

3 plans = 3 extra queries. 10 plans = 10 extra queries. Use a single annotated query:

```python
from django.db.models import Count

plans = SubscriptionPlan.objects.filter(is_active=True).annotate(
    active_count=Count(
        "subscriptions",
        filter=Q(
            subscriptions__status=SubscriptionStatus.ACTIVE,
            subscriptions__current_period_end__gte=today,
        ),
    )
).order_by("price_usd")
```

---

### HIGH-04 — Phone number format is not validated

**Location:** `subscriptions/serializers.py:SubscribeSerializer`

**Problem:**
`phone_number = serializers.CharField(max_length=20)` — any string up to 20 chars passes validation. `+44123456789`, `hello`, `00000000000` all pass. Paynow will reject invalid formats and the error bubbles up as a cryptic 502. Zimbabwe numbers follow specific patterns (263xx, 07xx).

**Fix:**
```python
import re

def validate_phone_number(self, value: str) -> str:
    value = value.strip().replace(" ", "").replace("-", "")
    if not re.match(r"^(263|0)(7[1-8])\d{7}$", value):
        raise serializers.ValidationError(
            "Enter a valid Zimbabwean mobile number (e.g. 0771234567 or 2637712345678)."
        )
    return value
```

---

### HIGH-05 — `CELERY_TASK_ALWAYS_EAGER = True` is a global hardcoded setting

**Location:** `config/settings.py:303`

**Problem:**
```python
CELERY_TASK_ALWAYS_EAGER = True
```
This is not conditional on DEBUG or environment. If someone deploys this to production without noticing, `process_paynow_callback.delay()` will **block the HTTP response** while polling Paynow synchronously. The Paynow webhook will time out waiting for your 200 response. Paynow will retry. You get a loop.

**Fix:**
```python
CELERY_TASK_ALWAYS_EAGER     = _TESTING  # Only eager in tests
CELERY_TASK_EAGER_PROPAGATES = _TESTING
```

---

### HIGH-06 — No Celery Beat schedule defined for `check_expired_subscriptions`

**Location:** `subscriptions/tasks.py:19` + `config/settings.py`

**Problem:**
The task is decorated with `@shared_task` and the docstring says "Runs daily (scheduled via Celery Beat)" — but there is no `CELERY_BEAT_SCHEDULE` in `settings.py`. The task simply does not run automatically. Expired subscriptions are never cleaned up. Readers keep premium access indefinitely after expiry.

**Fix:**
```python
# In config/settings.py:
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "check-expired-subscriptions": {
        "task":     "subscriptions.tasks.check_expired_subscriptions",
        "schedule": crontab(hour=0, minute=5),  # 00:05 Harare time daily
    },
}
```

---

### HIGH-07 — `get_or_set_cache` sleeps in the request thread

**Location:** `core/cache.py:44-46`

**Problem:**
```python
if cache.get(lock_key):
    time.sleep(0.05)   # 50ms blocking sleep
    value = cache.get(full_key)
```

This blocks a gunicorn/uWSGI worker for 50ms. With 4 workers and a cache miss storm (e.g., cache restart), you can have all 4 workers sleeping simultaneously, effectively halting the server. This is not a safe stampede-prevention pattern for synchronous Django.

**Fix:** Remove the sleep. Use probabilistic early expiration (XFetch) or just accept simultaneous recomputation for non-critical data. Alternatively use Redis `SET NX` for distributed locking via `cache.add()`.

---

### HIGH-08 — `CacheControlMixin` defaults to `Cache-Control: public`

**Location:** `core/cache.py:110-129`

**Problem:**
```python
class CacheControlMixin:
    cache_public: bool = True  # ← default is public
```

Any view that inherits `CacheControlMixin` without explicitly setting `cache_public = False` will serve `Cache-Control: public` headers. If any authenticated view accidentally inherits this, CDNs and Cloudflare will cache user-specific responses and serve them to other users. User A sees User B's data.

**Fix:** Default to `private`:
```python
cache_public: bool = False  # Safe default; set True only for truly public content
```

---

### HIGH-09 — Missing `SECURE_*` settings for production HTTPS

**Location:** `config/settings.py`

**Problem:**
None of the following are set:
- `SECURE_SSL_REDIRECT` — HTTP requests not redirected to HTTPS
- `SESSION_COOKIE_SECURE` — session cookie sent over HTTP
- `CSRF_COOKIE_SECURE` — CSRF token sent over HTTP
- `SECURE_HSTS_SECONDS` — no HSTS header

Readers can be MITMed over HTTP. Staff can have their session cookies stolen.

**Fix:**
```python
if not DEBUG:
    SECURE_SSL_REDIRECT       = True
    SESSION_COOKIE_SECURE     = True
    CSRF_COOKIE_SECURE        = True
    SECURE_HSTS_SECONDS       = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD       = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
```

---

### HIGH-10 — Revenue report uses `timezone.datetime` directly

**Location:** `subscriptions/views.py:524-526`

**Problem:**
```python
Payment.objects.filter(
    created_at__gte=timezone.make_aware(
        timezone.datetime(month_start.year, month_start.month, 1)
    ),
)
```

`timezone.datetime` is not a standard attribute. `django.utils.timezone` re-exports `datetime.datetime` but this is fragile. More critically, `make_aware()` with Africa/Harare's offset can produce unexpected results at DST boundaries (though Zimbabwe doesn't observe DST, this pattern is wrong).

**Fix:**
```python
import datetime
month_start_dt = datetime.datetime(month_start.year, month_start.month, 1, tzinfo=datetime.timezone.utc)
```

---

## 🟡 MEDIUM IMPROVEMENTS

---

### MEDIUM-01 — Paywall can be bypassed via token confusion

**Location:** `subscriptions/middleware.py:142-155`

**Problem:**
```python
def _is_staff_token(raw_token: str) -> bool:
    token = AccessToken(raw_token)
    return token.get("token_type") == "access"
```

This only checks `token_type == "access"`. It does not verify the token's signature against `SECRET_KEY` before extracting the claim, because `AccessToken(raw_token)` raises `TokenError` on invalid tokens — which is caught by the broad `except Exception`. But what about a reader token that somehow has `token_type == "access"` set? The reader JWT system uses different token types (`reader_access`) so this is fine now, but the validation logic is fragile. If a future developer changes token types, this silently breaks.

Also: the ENTIRE paywall check only runs for `GET`. A `HEAD /api/v1/articles/premium-slug/` request bypasses the paywall. Content metadata (title, excerpt) could be exposed.

**Fix:** Also intercept HEAD requests in the middleware.

---

### MEDIUM-02 — `AllSubscriptionsView` passes raw query param to ORM filter

**Location:** `subscriptions/views.py:485-487`

**Problem:**
```python
status_filter = self.request.query_params.get("status")
if status_filter:
    qs = qs.filter(status=status_filter)
```

An arbitrary string from the URL is passed to `qs.filter(status=...)`. Django handles this gracefully for simple fields, but it's bad practice. `?status='; DROP TABLE subscriptions; --` doesn't work in Django ORM but `?status=anything` returns an empty queryset silently. Validate against `SubscriptionStatus.values`.

---

### MEDIUM-03 — Subscription billing period is 30 days, not monthly

**Location:** `subscriptions/views.py:161-164`

**Problem:**
```python
if plan.billing_period == BillingPeriod.ANNUAL:
    period_days = 365
else:
    period_days = 30
```

Monthly billing is calculated as 30 fixed days, not one calendar month. A reader subscribing on January 31 gets access until March 1 (29 or 30 days), not February 28. Another subscribing on January 1 gets access until January 31. Inconsistent. Use `dateutil.relativedelta` for calendar-accurate billing.

---

### MEDIUM-04 — `plans/` endpoint has no caching

**Location:** `subscriptions/views.py:77-92`

**Problem:**
`PlanListView` queries the DB on every request with zero caching. This endpoint is called by every visitor to the pricing page. Plans change once in a blue moon. This should be cached for at least 10 minutes.

---

### MEDIUM-05 — `MySubscriptionView` returns 404 for readers with no subscription

**Location:** `subscriptions/views.py:120-124`

**Problem:**
Returning 404 when a resource legitimately doesn't exist is semantically correct for REST, but for a subscription status endpoint it's unusual. The frontend has to handle 404 as "no subscription" which is awkward. Consider returning `{"status": "none", "plan": null}` with 200, which is more ergonomic for the client.

---

### MEDIUM-06 — Decimal/float conversion in Paynow client is lossy

**Location:** `subscriptions/paynow_client.py:84`

**Problem:**
```python
payment.add("Granite Post Subscription", float(amount_usd))
```

`amount_usd` is a `Decimal`. Converting to `float` introduces floating point imprecision. `float(Decimal("2.00"))` is `2.0` which is fine, but `float(Decimal("1.99"))` could become `1.9899999999999...` which Paynow might round differently. Pass the Decimal as a string or use integer cents.

---

### MEDIUM-07 — `SubscribeView` creates subscription before confirming Paynow success, then deletes it on failure

**Location:** `subscriptions/views.py:191-218`

**Problem:**
The subscription is created at line 191, Paynow is called at 204-215, and if Paynow fails, `subscription.delete()` is called at 218. If `subscription.delete()` throws (DB connection loss, constraint violation), you have a TRIALING subscription with no Payment record and no way to identify it as abandoned. Over time these accumulate as ghost subscriptions.

Better pattern: Call Paynow first, create the subscription only on success.

---

### MEDIUM-08 — No Celery Beat for renewal reminders

**Location:** `subscriptions/tasks.py:71`

**Problem:**
`send_renewal_reminder` exists but is never scheduled and is a stub (only logs). There is no mechanism to actually fire it 3 days before expiry. The task is complete dead code.

---

### MEDIUM-09 — Revenue report is not cached

**Location:** `subscriptions/views.py:496-563`

**Problem:**
The revenue report runs 3+ DB queries (plus N per plan) on every request. This is a staff-only report that could be cached for 5 minutes with zero UX impact.

---

### MEDIUM-10 — `process_paynow_callback` leaks Paynow poll URL in logs

**Location:** `subscriptions/paynow_client.py:219`

**Problem:**
```python
logger.info("[Paynow] Polling payment status: url=%s", poll_url)
```

Paynow poll URLs contain a GUID that is effectively a payment token. Logging the full URL means anyone with log access can poll Paynow directly to check payment status for any reader. Truncate or hash in logs.

---

### MEDIUM-11 — Missing Content Security Policy header

**Location:** `core/middleware.py:80-94`

**Problem:**
`SecurityHeadersMiddleware` sets X-Frame-Options, X-Content-Type-Options, Referrer-Policy — but not CSP. Without CSP, any XSS vulnerability (e.g. in an admin template) can exfiltrate tokens. At minimum add `default-src 'self'` for the API.

---

### MEDIUM-12 — `requirements.txt` missing critical production dependencies

**Location:** `requirements.txt`

**Problem:**
- `celery` — not in requirements but used throughout
- `paynow` — not in requirements but imported in paynow_client.py
- `requests` — used in `cloudflare_purge.py`, not in requirements
- `python-dateutil` — would be needed if MEDIUM-03 is fixed
- No pinned minor versions (e.g. `celery>=5.3,<6.0`) — a major upgrade could silently break tasks

---

### MEDIUM-13 — `check_expired_subscriptions` has redundant `.count()` before `.update()`

**Location:** `subscriptions/tasks.py:38-40`

**Problem:**
```python
expired_count = expired_qs.count()   # DB query 1
if expired_count:
    expired_qs.update(...)            # DB query 2
```

Two queries when one suffices. `update()` returns the count of affected rows:
```python
expired_count = Subscription.objects.filter(...).update(status=SubscriptionStatus.EXPIRED)
```

---

## 🟢 LOW PRIORITY / CLEANUP

---

### LOW-01 — `uuid` import in `subscriptions/views.py` is unused
`import uuid` at line 25 is imported but never used. Dead import.

---

### LOW-02 — `settings` import in `subscriptions/views.py` is unused
`from django.conf import settings` at line 29 is never referenced. Dead import.

---

### LOW-03 — `Count` and `Q` imports in `subscriptions/views.py` are unused
`from django.db.models import Count, Q, Sum` — `Count` and `Q` are imported but only `Sum` is used.

---

### LOW-04 — `timedelta` imported in `subscriptions/tasks.py` but not used
`from datetime import date, timedelta` — `timedelta` is unused. The `send_renewal_reminder` stub used to use it but doesn't anymore.

---

### LOW-05 — `_SUBSCRIPTION_CACHE_TTL` constant defined but never used
`subscriptions/views.py:70` — `_SUBSCRIPTION_CACHE_TTL = 300` is defined but `_invalidate_reader_subscription_cache` uses a hardcoded key pattern, not this constant. The middleware uses `_CACHE_TTL = 300` (its own constant). Three places define the same TTL independently.

---

### LOW-06 — `AllSubscriptionsView` uses staff JWT but no explicit `authentication_classes`
The view uses `IsSeniorEditorOrAbove` permission but doesn't explicitly declare `authentication_classes`. It falls through to the DRF global default (`JWTAuthentication`). Works, but is implicit. Should be explicit for clarity.

---

### LOW-07 — `cancel_at_period_end` subscriptions don't deactivate cache on cancellation
When a reader cancels with `cancel_at_period_end=True`, the subscription remains ACTIVE and the cache is invalidated (correct). But `check_expired_subscriptions` then finalises the cancellation via bulk update — and as noted in CRITICAL-08, never clears the cache for these readers.

---

### LOW-08 — `tz` import inside function body in tasks.py
`from django.utils import timezone as tz` (line 49) is imported inside the function body and then never used. The `cancel_qs.update()` doesn't use it.

---

## 🚀 PERFORMANCE IMPROVEMENT PLAN

### Step 1 — Eliminate the middleware DB hit on every article (week 1)
Cache `(slug → is_premium)` in `PaywallMiddleware`. Every article request currently hits the DB twice (middleware + view). Caching the premium flag eliminates the middleware query for 99% of articles. Cost: 2 hours. Impact: significant at any traffic volume.

### Step 2 — Cache the paywall 402 upgrade plan list (week 1)
`_paywall_response()` queries plans on every 402. This is a completely static list. Cache it for 1 hour. Cost: 30 minutes.

### Step 3 — Fix the revenue report N+1 (week 1)
Replace the plan loop with a single annotated query (see HIGH-03). Cost: 1 hour. Impact: linear improvement with plan count.

### Step 4 — Cache the plan listing endpoint (week 1)
`PlanListView` has no cache. Add `CacheControlMixin` with `s-maxage=600` and a Redis-backed view cache. Cost: 30 minutes.

### Step 5 — Remove `time.sleep()` from `get_or_set_cache` (week 2)
The 50ms worker-blocking sleep is a latency bomb under load. Remove it. Cost: 1 hour.

### Step 6 — Add `select_related` to `MySubscriptionView` (already done) and audit all remaining views
The subscription views are mostly clean. Run `django-debug-toolbar` in staging and check for any remaining N+1s in articles, comments, and analytics.

### Step 7 — Cache the subscription status check in middleware with a warming strategy (week 3)
The current 5-minute TTL cache is good. Extend it by also warming the cache on subscription creation/cancellation (not just invalidation) so the first post-expiry article request doesn't miss.

### Step 8 — Add database-level indexes for subscription expiry queries (week 3)
`check_expired_subscriptions` does a full table scan on Subscription. Add a partial index:
```sql
CREATE INDEX sub_active_expiry_idx ON subscriptions_subscription (current_period_end)
WHERE status = 'active';
```

---

## 🧠 ARCHITECTURE IMPROVEMENT PLAN

### Fix NOW (before first real users)

1. **CRITICAL-01 through CRITICAL-09** — All critical payment race conditions and security holes must be resolved before accepting real money.

2. **Add `select_for_update()` to all payment state transitions** — Wrap every `payment.status = COMPLETED` in a transaction with row lock.

3. **Move `process_paynow_callback` to be the single activation path** — The poll endpoint (`PaynowPollView`) should NOT call `_activate_subscription()` directly. It should call `process_paynow_callback.delay()` and return a "processing" status. Single responsibility.

4. **Add `CELERY_BEAT_SCHEDULE`** — Without this, subscriptions never expire.

5. **Fix `CELERY_TASK_ALWAYS_EAGER`** — This one misconfiguration would break the entire payment webhook in production.

### Fix SOON (within first month)

6. **Subscription billing with calendar months** (MEDIUM-03) — 30-day billing creates customer support complaints immediately.

7. **Refactor `_activate_subscription` out of views into a service layer** — Payment activation logic is duplicated between `views.py` and `tasks.py`. Create `subscriptions/services.py:activate_subscription(payment_id)` as the single source of truth.

8. **Add a `SubscriptionEvent` audit log model** — Every status change (TRIALING → ACTIVE, ACTIVE → EXPIRED) should be recorded with a timestamp and trigger (manual/webhook/task). Without this you can't debug payment disputes.

9. **Validate PAYNOW credentials at startup** — If `PAYNOW_INTEGRATION_ID` or `PAYNOW_INTEGRATION_KEY` are empty and DEBUG=False, raise `ImproperlyConfigured`.

### Fix LATER (before scaling)

10. **Move subscription access checks to a dedicated service** — The paywall middleware, `PaynowPollView`, `process_paynow_callback`, and `check_expired_subscriptions` all implement overlapping subscription logic. Centralise in `subscriptions/services.py`.

11. **Consider a Paynow webhook signature verification** — If/when Paynow supports HMAC signing of callbacks, verify the signature in `PaynowCallbackView` before processing anything.

12. **Separate `subscription` (legacy/empty app) from `subscriptions` (new app)** — The codebase has both a `subscription` app (empty scaffold) and a `subscriptions` app (the real implementation). The legacy app clutters `INSTALLED_APPS` and `urls.py`. Delete it.

---

## ⚠️ HONEST VERDICT

**Is this production-ready?** No.

**Biggest risks if deployed today:**

1. **A reader can be charged without getting access** (CRITICAL-02) — non-atomic payment activation. This will cause support tickets within the first week of paid signups.

2. **OneMoney doesn't work at all** (CRITICAL-04) — hardcoded "ecocash" provider. Half your mobile payment methods are broken out of the box.

3. **Subscriptions never expire** (CRITICAL-08 + HIGH-06) — no Celery Beat schedule means `check_expired_subscriptions` never runs. Premium readers keep access forever. No recurring revenue.

4. **Duplicate subscriptions are possible** (CRITICAL-05) — a reader can pay multiple times for the same subscription period.

5. **Security** — default `SECRET_KEY` in production (CRITICAL-09) and missing HTTPS enforcement (HIGH-09) mean any deployment without careful env configuration is immediately exploitable.

**Technical debt level:** **High**

The architecture is fundamentally sound — the separation of apps, the JWT dual-user system, the middleware paywall pattern, and the Celery task structure are all reasonable designs. The models are clean and the serializers are well-structured.

But the payment layer was not sufficiently hardened before being called production-ready. The four issues that matter most (non-atomic activation, amount not verified, OneMoney hardcoded to EcoCash, duplicate subscriptions) are all in the same payment flow and would result in real financial harm to real users within the first month of operation.

Fix the 9 critical issues. Add the Celery Beat schedule. Test the full EcoCash payment flow end-to-end in Paynow's sandbox. Then it's deployable.
