# Procfile — The Granite Post API
#
# Three required processes for a complete production deployment:
#
#   web    — WSGI server (handles HTTP requests)
#   worker — Celery worker (processes async tasks)
#   beat   — Celery Beat scheduler (fires periodic tasks)
#
# All three must be running for the system to be fully operational:
#
#   - Payment callback processing (process_paynow_callback) needs worker.
#   - Subscription expiry checks (check_expired_subscriptions) need beat + worker.
#   - Renewal reminder emails (queue_renewal_reminders) need beat + worker.
#   - Transactional email delivery (accounts, newsletter) needs worker.
#
# If only the web process is started, async tasks will be silently queued in
# Redis and never consumed.  Use `celery inspect ping` to verify a worker
# is connected.
#
# Scaling:
#   - Scale web horizontally (multiple dynos / replicas).
#   - Run exactly ONE beat instance — multiple beat processes will double-fire schedules.
#   - Scale worker horizontally as task throughput demands.

web:    gunicorn config.wsgi:application --workers 4 --timeout 120 --bind 0.0.0.0:$PORT
worker: celery -A config worker --loglevel=info --concurrency=2 -Q celery,slow
beat:   celery -A config beat --loglevel=info
