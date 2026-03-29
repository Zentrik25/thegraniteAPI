# Deep Backend Audit - The Granite Post

This audit is based on the current codebase as checked in. File references use `path:line` notation.

### 🔴 CRITICAL ISSUES (must fix immediately)

1. Public paywall bypass and draft leak through section hero serialization
Evidence: `sections/models.py:42,106-108`, `sections/serializers.py:31,53-57`, `sections/views.py:97`, `articles/serializers.py:85-107`, `subscriptions/middleware.py:28-75`.
Why it’s dangerous: the paywall only intercepts `GET /api/v1/articles/<slug>/`. The public section detail endpoint can return `featured_article` serialized with `ArticleDetailSerializer`, which includes `body`. If editors pin a premium article, the full premium body leaks publicly. If they pin a draft or review article, unpublished content leaks publicly too. This is not theoretical. The current code allows it.
Exact fix: stop serializing `featured_article` directly on public section endpoints. Resolve hero content from a queryset constrained to `status=published` and, if the paywall must hold, exclude premium articles or return a paywalled summary serializer. Centralize article visibility rules in one shared selector/service instead of enforcing access in path-specific middleware.

2. Subscription and payment state is non-idempotent and race-prone
Evidence: `subscriptions/views.py:99,117,133,171,191,230,350,402,570`, `subscriptions/tasks.py:144,170-181,196`, `subscriptions/models.py:152-250,253-327`.
Why it’s dangerous: `SubscribeView` creates a new `Subscription` on every request and then a new `Payment` for paid plans. There is no idempotency key, no uniqueness constraint preventing multiple `ACTIVE` or `TRIALING` subscriptions per reader, no uniqueness on `Payment.paynow_reference`, and activation is done by plain save calls with no `transaction.atomic()` or `select_for_update()`. A double-click, retry storm, or concurrent webhook plus poll can leave multiple live subscriptions or inconsistent payment state. `MySubscriptionView` then returns the newest row, not the active one, so the frontend and paywall can disagree.
Exact fix: introduce a real payment state machine. Add a conditional unique constraint for one `ACTIVE` and one `TRIALING` subscription per reader, enforce idempotency on subscribe, store a merchant reference separately and uniquely, lock the `Payment` row with `select_for_update()` during activation, and make activation conditional on `status=PENDING` -> `COMPLETED` so repeated callbacks are harmless.

3. Celery is hardwired to run synchronously in every environment
Evidence: `config/settings.py:307-308`, `core/signals.py:8-21`, `accounts/views.py:94,432`, `notifications/signals.py:39`, `articles/signals.py:89`, `core/tasks.py:18-156`.
Why it’s dangerous: `CELERY_TASK_ALWAYS_EAGER = True` means production requests execute “async” work inline. Registration, password reset, cache invalidation, sitemap pings, push fanout, payment retries, and image processing all run in the request/save path. That destroys latency, magnifies third-party outages, and makes any network hiccup a user-facing failure.
Exact fix: make eager mode test-only, not global. Run a real broker and workers in production. Push every network side effect onto `transaction.on_commit()` + Celery tasks. Anything external to the DB should be off the request thread.

4. Account verification, password reset, and newsletter email flows are not implemented and they leak live tokens into logs
Evidence: `accounts/tasks.py:4-6,16,43-49,84-90`, `newsletter/tasks.py:21,29-35,61-62`.
Why it’s dangerous: these tasks are stubs. They do not send real email. They log verification URLs, password reset URLs, and confirmation URLs containing live tokens. In production that means readers cannot complete basic auth flows while your logs become a token exfiltration surface.
Exact fix: wire a real mail provider now. Remove token-bearing log lines entirely. Make frontend base URLs environment-driven, not hardcoded to `https://thegranite.co.zw`.

5. The dependency manifest does not contain several packages that the runtime imports
Evidence: `subscriptions/paynow_client.py:39`, `core/cloudflare_purge.py:42`, `notifications/tasks.py:4,112`, `accounts/tasks.py:12`, `newsletter/tasks.py:3`, `media_assets/models.py:44`, versus `requirements.txt:1-28`.
Why it’s dangerous: a clean deploy or autoscaled node can boot successfully and then crash the first time a payment, push, media, or task path is exercised. Missing packages here include `celery`, `paynow`, `requests`, `pywebpush`, and `Pillow`.
Exact fix: add every runtime dependency to `requirements.txt`, pin versions, and add a CI smoke test that installs from scratch and imports the full Django app registry.

### 🟠 HIGH PRIORITY IMPROVEMENTS

1. Paynow callback handling is not authenticated and not rate-limited
Evidence: `subscriptions/serializers.py:191-202`, `subscriptions/views.py:350,383,393`, `subscriptions/tasks.py:167,196`.
Impact: the callback accepts unauthenticated POSTs, ignores any integrity proof, and immediately enqueues processing. Because activation ultimately polls Paynow, straight fraud is harder, but abuse is still easy: callback spam, worker churn, pointless retries, and operational noise. Paynow’s own docs expose notification payload handling and hash verification helpers, and this code uses none of that.
Recommended change: validate the callback payload cryptographically per the official Paynow docs, add throttling, and reject unknown or malformed callback bodies before enqueuing any work.

2. OneMoney is advertised but the payment client hardcodes EcoCash
Evidence: `subscriptions/serializers.py:125-127`, `subscriptions/views.py:203`, `subscriptions/paynow_client.py:52,86`.
Impact: the API accepts `onemoney` as a valid payment method, but the gateway call always sends `"ecocash"`. That means one of your advertised payment paths is fake.
Recommended change: either remove `ONEMONEY` from the API until it is really supported, or pass the requested mobile money method through to the Paynow client and cover it with tests.

3. Article permissions are inconsistent and tied to raw Django staff flags instead of the project’s role model
Evidence: `articles/views.py:51,73,79,96`, `users/permissions.py`.
Impact: article creation is gated by `IsAdminUser`, which means Django `is_staff`, not editorial role. At the same time authors can edit their own articles through a custom object permission. This is inconsistent, violates the project’s own documented role model, and invites privilege drift if anyone ever toggles `is_staff` manually.
Recommended change: replace `IsAdminUser` and raw `request.user.is_staff` checks with explicit role permissions everywhere.

4. `MySubscriptionView` returns the newest subscription row, not the current effective subscription
Evidence: `subscriptions/views.py:99-117`.
Impact: if a reader has an active subscription and then starts a second pending subscription, the API will return the newest `TRIALING` row. The paywall middleware independently checks for any active premium subscription. Result: frontend state and backend access decisions diverge.
Recommended change: return the effective subscription, not the newest row. Prioritize `ACTIVE` with unexpired period, then `TRIALING`, then historical fallback.

5. Several public endpoints over-fetch and skip pagination entirely
Evidence: `articles/views.py:178-214`, `users/views.py:33-49`, `sections/serializers.py:31-68`.
Impact: category detail, tag detail, user detail, and section detail can dump large arrays of articles in one response. On a real newsroom with years of content, that becomes slow, memory-heavy, and frontend-hostile.
Recommended change: paginate article collections consistently. Keep the metadata object separate from a paginated `articles` envelope.

6. Search leaks premium body snippets and the API contract is internally inconsistent
Evidence: `search/views.py:139-150,173-184,219-221`, `search/serializers.py:6-15`.
Impact: search runs against all published articles, including premium ones, and returns `headline` built from `body` text. That leaks body-derived premium content through a public endpoint. On top of that, the serializer/schema does not declare `headline`, so your docs are lying.
Recommended change: either exclude premium articles from public search or replace `headline` with a teaser sourced from `excerpt`. Update the serializer/schema to match the actual response.

7. Media detail leaks other authors’ asset metadata
Evidence: `media_assets/views.py:47-55`, `media_assets/views.py:118-137`.
Impact: list view correctly limits non-editors to their own assets, but detail view does not. Any authenticated author who guesses an asset ID can retrieve someone else’s media metadata and CDN URL.
Recommended change: apply the same ownership/editor rule in `MediaDetailView.get()` that is already used in delete and list.

8. Production security configuration is incomplete and dangerously forgiving
Evidence: `config/settings.py:27`, `config/settings.py:315`, and the absence of `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, and `SECURE_HSTS_PRELOAD`.
Impact: the app will start with a known fallback secret key if `SECRET_KEY` is missing, and it lacks the standard secure-cookie / HSTS / SSL redirect hardening expected for production. That is basic deployment hygiene, not optional polish.
Recommended change: fail fast when `DEBUG=False` and `SECRET_KEY` is unset or default. Add the missing HTTPS and cookie security settings behind environment flags.

9. IP-based throttling, analytics, and ad dedupe can be spoofed
Evidence: `core/cloudflare.py:61-87`, `core/middleware.py:128-140`, `analytics/models.py:31-32`, `advertising/models.py:240`, `comments/models.py:74`.
Impact: outside the Cloudflare-specific branch, the code trusts the first `X-Forwarded-For` value. If the app is ever reachable without a proxy that strips spoofed headers, a client can rotate fake IPs to bypass throttles, pollute analytics, and defeat impression dedupe.
Recommended change: trust forwarded headers only from explicitly trusted upstream proxies. Otherwise use `REMOTE_ADDR`.

### 🟡 MEDIUM IMPROVEMENTS

1. Public serializers and views still contain obvious N+1 query traps
Issue: `UserPublicSerializer.get_article_count()` runs a count per user, `Section.article_count` and `Section.category_count` are property-backed queries per section, and comments prefetch `replies` in the view only for the serializer to re-query filtered replies per comment.
Evidence: `users/serializers.py:9,27`, `sections/serializers.py:13-14`, `sections/models.py:74-83`, `comments/views.py:58`, `comments/serializers.py:27-33`.
Suggested improvement: annotate counts in the queryset, prefetch filtered replies with `Prefetch`, and stop doing counting work inside serializer methods/properties.

2. The push-notification fanout is a serial loop that will collapse under load
Issue: push sends iterate every active subscription one by one.
Evidence: `notifications/tasks.py:32,54,67,167`.
Suggested improvement: batch subscribers, shard work across tasks, and stop doing naive per-recipient loops if this is expected to serve real audience scale.

3. The cache “stampede protection” is fake
Issue: `get_or_set_cache()` uses `cache.set(lock_key, True)` without an atomic add/SETNX semantics.
Evidence: `core/cache.py:31-50`.
Suggested improvement: use Redis `SET NX EX`, Django cache `add()`, or a real lock implementation. Right now multiple workers can all compute the same expensive payload.

4. Section caches are set but never explicitly invalidated on update or delete
Issue: public section list/detail responses are cached, but patch/delete paths do not clear those keys.
Evidence: `sections/views.py:23-24,61,110,117,134`.
Suggested improvement: invalidate section list/detail caches on write or move section caching into a consistent cache service with explicit invalidation hooks.

5. Subscription expiry handling is logically wrong and cache invalidation is incomplete
Issue: `check_expired_subscriptions()` first marks expired active subscriptions as `EXPIRED`, then looks for `ACTIVE` + `cancel_at_period_end=True`, so those rows never become `CANCELLED`. It also logs that cache invalidation should happen but does not actually invalidate per-reader access caches.
Evidence: `subscriptions/tasks.py:34-40,51-68`, `subscriptions/middleware.py:197`, `subscriptions/views.py:592-595`.
Suggested improvement: split the `cancel_at_period_end` update before the generic expiry update, and invalidate cached subscription status for affected readers.

6. Logging is not actually structured despite the middleware pretending it is
Issue: middleware attaches `extra` fields like request ID, path, IP, and user agent, but the configured formatter only renders `{levelname} {asctime} {name} {message}`.
Evidence: `core/middleware.py:59-71`, `config/settings.py:270-282`.
Suggested improvement: either emit real JSON logs or include the extra fields in the formatter. Right now you pay the complexity cost without getting structured observability.

7. Breaking-news notification logic is wrong
Issue: the post-save signal reloads the just-saved article from the database and compares `old.is_breaking` after the save, so updates from `False` -> `True` are treated as already breaking and skipped.
Evidence: `notifications/signals.py:31-39`.
Suggested improvement: capture prior state in `pre_save` or query the previous row before the save, not after it.

8. The caching and invalidation architecture is only half-used
Issue: there is a lot of cache key infrastructure and warm/invalidate tasks, but the main article/feed views do not actually read from that cache layer.
Evidence: `core/tasks.py:18-146`, `articles/views.py:118-214`, `core/cache.py:62-132`.
Suggested improvement: either commit to response caching and wire views through it, or delete the dead cache-warming complexity.

9. The test suite misses the exact failure modes that matter most
Issue: there are tests for happy-path subscriptions, but nothing for concurrent activation, duplicate subscribe requests, OneMoney, callback signature verification, or the section-based paywall bypass.
Evidence: `subscriptions/tests.py:316,426,442` and no coverage for those cases.
Suggested improvement: add concurrency/idempotency tests, paywall leak tests, and malicious callback tests before touching production payments.

10. The codebase claims SQLite fallback but core search remains PostgreSQL-specific
Issue: the search stack depends on `SearchVectorField`, `SearchQuery`, `SearchRank`, and `SearchHeadline`.
Evidence: `articles/models.py:17-18,273-279`, `search/views.py:2-9,139-184`.
Suggested improvement: either document search as PostgreSQL-only or provide a dev fallback path that doesn’t explode outside Postgres.

### ?? LOW PRIORITY / CLEANUP

1. `core.views.APIRootView` advertises `authors` at `/api/v1/authors/`, but the real endpoint is `/api/v1/users/`.
Evidence: `core/views.py:60-78`, `users/urls.py`.

2. The project mounts both `subscription` and `subscriptions`, but `subscription` is an empty scaffold.
Evidence: `config/urls.py:54-55`, `subscription/urls.py:5`, `subscription/views.py:3`.

3. `ArticleListSerializer` returns the display label for `status` while write endpoints expect the machine value. That inconsistency is avoidable noise for clients.
Evidence: `articles/serializers.py:39-63`.

4. The paywall response hardcodes `upgrade_url` as `/subscription/upgrade/`, which is not derived from config and may drift from the real frontend route.
Evidence: `subscriptions/middleware.py:118-125`.

5. There are multiple placeholders and “stub” code paths still living in production-facing apps: image processing, emails, subscription reminders, and the empty subscription scaffold.

### ?? PERFORMANCE IMPROVEMENT PLAN

1. Turn off eager Celery in production and move every external call off the request/save path.
2. Fix the public over-fetching endpoints by paginating category, tag, author, and section article collections.
3. Remove N+1 queries in users, sections, comments, and any serializer method that counts or filters related objects per row.
4. Put the paywall in the data access layer so public aggregations cannot accidentally serialize restricted content.
5. Decide whether the cache layer is real or fake. If real, wire hot public GET endpoints through it and invalidate on writes. If not, delete the dead warming/invalidation machinery.
6. Batch notification fanout instead of looping every subscription serially.
7. Add DB-level constraints for subscription/payment uniqueness so the database stops invalid states instead of merely hoping the view logic behaves.
8. Add query observability in production: slow-query logging, request tracing, and DB/Redis metrics.

### ?? ARCHITECTURE IMPROVEMENT PLAN

Refactor NOW:
- Replace middleware-only paywall enforcement with a shared article visibility policy used by all public serializers and selectors.
- Rebuild subscriptions/payments as a proper transactional state machine with idempotency, locks, and DB constraints.
- Remove global eager Celery and finish the email pipeline.
- Eliminate raw `is_staff` permission decisions in favor of the editorial role system.
- Clean up missing dependencies and production security settings before deployment.

Refactor LATER:
- Collapse the `subscription` vs `subscriptions` confusion into one app.
- Replace serializer-level counting with annotated queryset services.
- Normalize caching behind a dedicated service instead of scattering keys and ad hoc invalidation across apps.
- Break out third-party integrations (Paynow, Cloudflare, push) behind service interfaces with typed results and stronger testing.

### ⚠️ HONEST VERDICT

Is this production-ready? No.

Biggest risk if deployed today: you can leak premium or unpublished article bodies publicly while the payment/subscription layer simultaneously creates inconsistent billing state and blocks real user flows like verification and password reset.

Technical debt level: Critical.

