# Shop deployment and operations

## Upgrade and compatibility

Install `requirements.txt`, then run `python manage.py migrate` before starting
workers. Run `python manage.py collectstatic --noinput` and configure the web
server to serve STATIC_ROOT under `/static/` (including admin assets). Use a
production WSGI/ASGI server rather than runserver. Use PostgreSQL for row locking. Set a fresh private SECRET_KEY
and rotate all previously committed Paymob secret/API/HMAC keys in the dashboard.
Historical secrets remain in Git history. `.env.example` has placeholders only;
Django does not load this example. Use an ignored `.env` or host secret store.

New registrations require email verification for JWT login. The migration keeps
existing accounts accessible by marking them verified; this preserves access and
does not establish historical email ownership. Email changes require verification
of the new address. Mail links use the fixed HTTPS origin PUBLIC_BASE_URL.
Verification links require a confirmation POST and expire in 24 hours. Password
reset links expire in one hour and are single-use, with password validators.
Password changes invalidate existing access and refresh JWTs. Upgrading enables
password-bound JWTs, so pre-upgrade JWTs require a fresh sign-in once.

Account endpoints:
- POST `/api/register/`: username, email, password; verification mail follows.
- POST `/api/resend-verification/`: email; generic response.
- POST `/api/password-reset/`: email; generic response and reset mail if eligible.
- Existing login `/api/api/token/` and refresh `/api/api/token/refresh/` remain.

Catalog GET `/api/products/` now returns `{count,next,previous,results}` instead of
a bare array. Clients must read `results`. Search uses `search`; allowed `ordering`
values are id, title, price and their `-` variants. `page_size` defaults to 24 and
is capped at 100; `page` selects the page.

## Authentication and edge limits

Token login/refresh and admin sign-in use shared database limits: 30 requests per
minute/source and 10/minute/account. Email endpoints allow 10/hour/source and
3/hour/address. Configure the trusted server/proxy to supply the source in
REMOTE_ADDR. Never copy arbitrary client forwarding headers. Add edge connection,
request and body limits for distributed attacks. Periodically prune expired rate
buckets. The application caps normal request bodies at 64 KiB.

## Mail, monitoring and attention queue

Configure EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS, EMAIL_HOST_USER,
EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, SERVER_EMAIL and comma-separated
ADMIN_EMAILS. DEBUG=False enables default server error emails. Newly flagged
payments send an operator email after commit. The durable queue is
`/admin/payments/payment/?needs_attention__exact=1`. A mail outage is logged and
cannot roll back an already committed payment. Verify actual delivery before
launch, monitor stdout/stderr, and alert on failed/missed timer jobs. A separate
Sentry account is not required by this implementation.

## Fulfillment

Order status/totals, payment status and order lines are protected from arbitrary
admin editing. Enter a tracking number, then use Mark shipped and Mark delivered.
The service enforces paid -> shipped -> delivered, a successful unrefunded payment,
and absence of an unresolved refund. Actor and time are recorded for each step.

## Refunds

The Payment admin provides Request full refund for authorized staff. Full refunds
only are supported. Partial refunds/physical returns require an operator process.
Refunds do not automatically restock products or change the order status.

Set the separate legacy PAYMOB_API_KEY for `/api/auth/tokens`. Full refund requests
use `/api/acceptance/void_refund/refund`, with the original transaction ID and
amount_cents. Validate that API/key with your Egypt merchant test account before
using production staff actions; the automated suite uses mocked provider traffic.
The documentation portal was unavailable during this sandbox run, so a live
provider contract check remains required. No real refund was issued here.

A permanent one-per-payment request prevents repeat submissions. Uncertain HTTP
outcomes are marked Needs reconciliation; clicking again reuses the request.
An identified signed refund result completes a pending request. Dashboard events
are recorded for review: the original transaction HMAC does not authenticate the
cumulative refunded amount, so the application never infers a full refund from
that amount. After independently checking the full refund in Paymob, run:

```bash
python manage.py reconcile_refund PAYMENT_ID --provider-id VERIFIED_REFUND_TRANSACTION_ID --amount-cents VERIFIED_FULL_AMOUNT --operator STAFF_USERNAME
```

This command records accounting only; it sends no refund. Never delete a refund
request to retry a possibly completed transfer. Partial refunds remain manual.
Old checkout identity reconciliation follows `payments/RECONCILIATION.md`.

Set PAYMOB_NOTIFICATION_URL to this app's public `/api/payments/webhook/` and verify
a test payment/refund callback. Invalid-signature payloads are rejected without
storage. Authenticated events are retained for 30 days; unresolved old checkout
identities preserve events needed for reconciliation.

## Scheduling and backups

Included systemd units are templates. Adjust paths/user, set private settings in
`/etc/antique.env` (mode 600), and create `/var/backups/antique` with mode 700 owned
by the service user. Install the unit files, then enable:

```bash
systemctl enable --now antique-maintenance.timer antique-backup.timer
```

For other hosts schedule cancel_expired_orders and prune_operational_data every
minute, and backup_database --directory PRIVATE_PATH daily. This commit does not
enable remote host timers. `pg_dump` must match the PostgreSQL server major version.
SQLite uses its online backup API and an integrity check. Backups are private,
timestamped and never overwritten. They contain personal data: copy them to
encrypted off-host storage, define retention and alert on missed copies/jobs.
External storage credentials/configuration must be supplied by the deployment.

Restore drills must use an isolated target, never the shop database:

```bash
createdb antique_restore_test
pg_restore --exit-on-error --no-owner --no-acl --dbname antique_restore_test BACKUP.dump
```

Check expected rows and application reads against the restored target. For SQLite
copy a backup to a disposable path, run PRAGMA integrity_check and application
reads. Record restore success and recovery time before launch; local backups alone
do not establish off-host protection.

## Overview reporting dates and shipping queue

The overview's To ship count and linked order list require a paid order, a
successful payment matching its total, and no refund ledger on any payment.
Tracking can be entered before using the guarded Mark shipped action. A pending
or uncertain refund blocks fulfillment and is excluded from this queue.

Migration payments.0004 adds nullable succeeded_at. Newly confirmed payments
record the first accepted successful callback time; duplicate callbacks, notes,
refunds and reconciliation edits do not move that date. Daily sales use this
confirmation time in Africa/Cairo. It is the time this shop confirmed success,
not an assertion about the provider's settlement time. Delayed confirmations
are counted on the day they are accepted.

Historical payments keep an unknown confirmation time: the migration does not
invent dates from checkout creation or mutable update times. They remain in
lifetime revenue and paid-order totals but are excluded from the daily chart,
with an explanatory count displayed. Run migrations before starting the updated
application. Refund accounting and fulfillment permissions are unchanged.
