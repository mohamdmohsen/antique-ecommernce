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

## Trusted Nginx client addresses

The throttle now resolves X-Real-IP only when REMOTE_ADDR belongs to an explicit
TRUSTED_PROXY_CIDRS network. Default trust is empty. X-Forwarded-For is ignored;
a malformed/multi-address header falls back to the direct peer. This resolver is
shared by API login, email, admin login and webhook limits, and HTML account forms.

For a single Nginx instance directly facing customers on the same host:

1. Bind Gunicorn only to private TCP `127.0.0.1:8000`; block public access to it.
   Use your production process manager, for example
   `gunicorn antique.wsgi:application --bind 127.0.0.1:8000 --workers 3`.
2. Adapt deployment/nginx.example.conf: set your domain, TLS certificates and
   static/media paths. It OVERWRITES X-Real-IP with `$remote_addr` and
   X-Forwarded-Proto with `$scheme`, and removes incoming forwarding chains.
3. Set `BEHIND_PROXY=True` and `TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128`
   in the application environment. Trust only Nginx's actual peer addresses.
   Do not use `0.0.0.0/0` or broad networks shared with untrusted workloads.
4. Run `nginx -t`, restart the application and reload Nginx on the deployment host.
5. From TWO distinct external clients, verify distinct login/email source buckets.
   On a staging account, changing client-supplied X-Real-IP/X-Forwarded-For must
   not change the derived client identity. Keep account-based throttling active.

A Unix socket has no IP peer and is NOT trusted by this configuration. Use the
private TCP example or separately design and test a secure socket integration.
With a load balancer/CDN before Nginx, first configure Nginx's real-IP module to
trust ONLY that provider's documented proxy networks; otherwise `$remote_addr`
is still the balancer. Never copy an arbitrary first forwarding-chain entry.
These are deployment templates, not proof of the running host's configuration.
A real-host check still needs the deployed URL and access to its proxy config.

## Checkout initialization without a provider-spanning database lock

Migration payments.0005 adds durable intention_state. A short transaction reserves
one pending payment as `creating`, then commits BEFORE Paymob HTTP. A second click
gets HTTP409 while initialization is running; once ready, repeated requests reuse
the same checkout URL with HTTP200. API errors include an additive `code` field. Clients should show a short retry
prompt for409 `busy`; `needs_review` must not be automatically retried.

Timeouts, malformed responses or process interruption do not free the reservation
or stock. Unknown outcomes need operator review; automatic retries cannot prove
that the provider did nothing. A crashed `creating` reservation also stays blocked.
Use reconcile_payment with an independently verified provider order ID and replay
stored signed callbacks. Identity alone, without a usable checkout secret, does
not authorize creation of another intention. Never reset/delete reservations to
retry a possibly completed operation. Pending identity problems preserve webhook
history during pruning. The provider's socket timeout is not a hard overall
wall-clock deadline, but it no longer keeps order rows locked.

## Customer storefront

Claude's feature branch supplied service extraction, English/Arabic strings,
optional Arabic product fields, font assets, preference middleware/context helpers
and template filters. It did not include a connected storefront. The integrated
repair adds registered web routes, forms, templates and CSS:

- `/`: searchable, sorted, paginated collection; `/pieces/ID/`: product detail.
- `/create-account/`, `/sign-in/`, `/forgot-password/`, `/resend-verification/`.
- `/cart/`, `/checkout/`, `/orders/`, `/orders/ID/`, POST-only payment redirect.
- Language/dark-mode preferences via CSRF-protected POSTs; Arabic uses RTL.

All mutations use CSRF-protected forms and the shared domain services. HTML
sessions require a verified active account; existing JSON APIs retain JWT auth.
Order/payment pages enforce ownership. Provider redirect parameters never establish
payment success: only the local database, updated by verified callbacks, does.
Set PAYMOB_REDIRECTION_URL to your public `/payment-result/`; the page redirects
the authenticated customer to their last payment order. Continue to configure
PAYMOB_NOTIFICATION_URL for the signed webhook. No external frontend build or
JavaScript is required. Run migrate (catalog0004, payments0005) and collectstatic
before deployment. Supply real product photos/translations and test SMTP and a
merchant sandbox checkout/callback before public launch.


## El sese bazzar policies and age declarations

Public English/Arabic pages: `/terms/`, `/privacy/`, `/returns/`, `/contact/`.
Policy text lives in `web/legal.py`; declaration version is
`users.policies.POLICY_VERSION`. When changing terms or declarations, update the
version and keep previous wording in version control. Existing acceptance rows
remain attached to their original version and timestamp; no historical consent
is invented. Apply `users.0003_policy_acceptance` before serving this version.
The admin provides a view-only Policy acceptances list. These records are
self-declarations, not proof of age, identity, parental consent or legal capacity.
No birth date or identity document is collected by this feature.

Intentional API input change (old payloads now return400):

- `POST /api/register/`: add `age_confirmed: true` and
  `terms_accepted: true` to username/email/password. Age confirmation declares13+
  and guardian management/permission when legal capacity is lacking.
- `POST /api/order/checkout/`: add `terms_accepted: true` and
  `buyer_confirmed: true` to delivery details. Buyer confirmation declares legal
  capacity; a child’s purchase must be made in the adult guardian’s own account.
- Omitted/false declarations create neither account nor order. API clients must
  show the actual policy links and statements, not silently supply these flags.
  Terms agreement also acknowledges the Privacy and Returns notices; it is not a
  marketing opt-in or a substitute for any separate consent required by law.
- HTML signup/checkout require the same confirmations. New declarations and the
  account/order are committed together. Existing accounts/orders are not
  backfilled, reclassified by age, or blocked from viewing/paying old orders.
  Admin-created accounts remain possible; existing customer age is unknown.

Before public trading, complete these public settings (not SMTP credentials):
`SHOP_LEGAL_NAME`, `SHOP_SUPPORT_EMAIL`, `SHOP_BUSINESS_ADDRESS`, `SHOP_PHONE`,
and applicable `SHOP_REGISTRATION_DETAILS` (registration/tax identification).
The brand name El sese bazzar does not by itself identify the legal seller.
Unknown details are explicitly shown as unpublished, with a pre-launch warning;
there is no made-up email address. This warning does not technically disable
checkout: keep the shop off public sale until details and operations are ready.
`manage.py check --deploy` warns about missing details or an invalid support
email. Do not use internal alert or SMTP login addresses as public contact
without deliberately choosing them for that purpose.

Have an Egyptian adviser review the actual business and policies, especially
children’s data and verified guardian consent, legal capacity, applicable data
protection requirements, taxes/invoices, returns/cancellation deadlines,
provenance of vintage goods and restrictions on protected antiquities. The13+
account rule is a shop rule, not a legal contracting or data-consent threshold.
There is no age/guardian-verification process in this feature. A checkbox cannot
prove compliance, prevent claims or waive mandatory consumer protections.

Verify before taking payment: publish delivery destinations, expected dates,
all charges/taxes and any guarantee; establish a real support/return process and
return address; identify hosting/email/courier providers, processing locations,
retention/backup deletion schedule and privacy-request handling. None of those
provider identities, shipping promises or legal/tax registrations are invented
by these templates. This commit does not implement partial Paymob refunds or
new delivery charges; confirm the existing full-refund service fits each claim.

Research reference: Egypt Consumer Protection Agency’s published Law181/2018,
https://cpa.gov.eg/Portals/0/Law/CPA-Newlaw.pdf . Articles17/21 address general
14-day returns (with exceptions) and30-day defective/nonconforming remedies;
article37 requires distance sellers to provide identity/contact and transaction
details. Read these with applicable distance-sale provisions, exceptions,
regulations and later changes; do not treat a vintage label as a blanket return
exemption. Source was visually checked against the official PDF on2026-10-29;
this is a starter implementation, not a legal compliance certification.
