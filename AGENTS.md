# AGENTS.md — The Granite Post Backend

## Project
Django 6 + DRF editorial CMS API for The Granite Post (Zimbabwe news platform).
Consumed by a Next.js frontend at `http://localhost:3000`.

## Stack
- **Runtime:** Python 3, Django 6.0, Django REST Framework 3.15
- **Auth:** SimpleJWT (60-min access / 7-day refresh, rotate + blacklist)
- **DB:** PostgreSQL (production), SQLite (dev fallback via `DATABASE_URL` env)
- **Cache/Throttle:** Redis (2 caches: `default` + `throttle`); LocMemCache in tests
- **Tasks:** Celery (always-eager in dev/test; Redis broker in production)
- **Schema:** drf-spectacular → OpenAPI 3 at `/api/schema/`, Swagger at `/api/docs/`
- **Static:** WhiteNoise

## Apps & Responsibilities

| App | Purpose |
|-----|---------|
| `users` | `StaffUser` (custom AbstractUser), roles, JWT, author profiles |
| `articles` | Articles, Categories, Tags — full editorial workflow |
| `core` | Shared: pagination, throttling, middleware, JWT customisation, exceptions |
| `analytics` | `PageView` tracking & metrics |
| `comments` | Reader comments + moderation |
| `newsletter` | Email subscriptions |
| `feeds` | RSS feeds + Django sitemaps |
| `media_assets` | Image/file uploads, S3 storage layer, validators |
| `search` | PostgreSQL full-text search (`SearchVectorField`, GIN index) |
| `sections` | (Scaffolded, not yet wired) |

## API Routes (prefix `/api/v1/`)

```
articles/…          articles, categories, tags
users/…             public author profiles
staff/…             staff management (Senior Editor / Admin only)
analytics/…         page view tracking
comments/…          reader comments
newsletter/…        subscription endpoints
media/…             upload/manage assets
search/…            full-text search
auth/token/         obtain JWT pair
auth/token/refresh/ refresh access token
auth/token/blacklist/ logout
```

Non-API routes: `/admin/`, `/health/`, `/feed/…`, `/sitemap.xml`, `/api/schema/`, `/api/docs/`

## Roles & Permissions
`Contributor < Author < Moderator < Editor < Senior Editor < Admin`

Role permissions are auto-synced to Django groups via `users.models.StaffUser`.
Always use `request.user.role` checks in DRF permissions, never raw `is_staff`.

## Data & Models — Key Facts
- `Article` status flow: `draft → review → published → archived`
- Slug generation: auto with collision detection (counter loop → UUID fallback)
- Top stories: 6-slot grid, DB-enforced unique `position` per slot
- Breaking news: boolean flag, short TTL cache (30s)
- `SearchVectorField` on `Article` — rebuild with `python manage.py rebuild_search_index`
- PostgreSQL GIN indexes on search vector and tags

## Cache Keys & TTLs
Defined in `CACHE_KEYS` and `CACHE_TTL` in `config/settings.py`.
Always invalidate relevant cache keys after any write that changes public content.

## Coding Rules
- **Never** put service-role or secret keys in any file that ships to the frontend.
- **Always** use the structured exception handler (`core.exceptions.structured_exception_handler`) — never raise raw `Exception`.
- New apps must register in `INSTALLED_APPS` in `config/settings.py` and wire URLs in `config/urls.py`.
- Migrations live under each app's `migrations/` directory. Generate with `makemigrations <app>`, never edit generated files by hand unless unavoidable.
- When adding a model field: update the serializer, the admin, and the OpenAPI schema hints (`@extend_schema`).
- Throttle classes: `core.throttling.RoleBasedThrottle` + `BurstRateThrottle` — respect existing rate-limit tiers.
- Pagination: `core.pagination.StandardResultsPagination` (page_size=20).
- Timezone: `Africa/Harare` — always store datetimes as UTC, display in local tz.

## Testing
```bash
python manage.py test                        # all tests
python manage.py test articles               # single app
python manage.py test --keepdb               # skip DB re-creation
```
Tests use `LocMemCache` (Redis not required). Celery tasks run eagerly (`CELERY_TASK_ALWAYS_EAGER=True`).

## Common Commands
```bash
# Dev server
python manage.py runserver

# Migrations
python manage.py makemigrations <app>
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Rebuild search index
python manage.py rebuild_search_index

# Check for issues
python manage.py check --deploy

# Collect static (production)
python manage.py collectstatic --noinput
```

## Environment Variables
| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `true` / `false` |
| `ALLOWED_HOSTS` | Comma-separated host list |
| `DATABASE_URL` | PostgreSQL DSN (omit for SQLite) |
| `REDIS_URL` | Redis DSN for cache + Celery |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins |
| `MAINTENANCE_MODE` | `true` to return 503 on all requests |

## Non-Negotiables
- Public endpoints must only return `published` content — never expose `draft` or `review` articles.
- All write endpoints require authentication; destructive actions require appropriate role.
- Rate limiting is active on all endpoints — do not remove throttle classes.
- `StaffUser` is the only user model (`AUTH_USER_MODEL = "users.StaffUser"`); never reference `django.contrib.auth.User`.
