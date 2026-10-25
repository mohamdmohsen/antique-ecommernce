# Existing checkout reconciliation

A checkout with a client secret but no `paymob_order_id` may still accept money.
The application preserves it, returns HTTP 409 when payment is retried, flags it
for review, and holds its stock when the expiry command runs. New checkouts and
ordinary unpaid orders keep their existing behavior.

For each affected payment, verify the original provider order ID against that
payment's checkout in Paymob's authenticated dashboard or API. Check the merchant
reference, amount and currency there. Do not derive the identity from an incoming
callback's unsigned `merchant_order_id`.

Once verified, run with the deployment's normal environment:

```bash
python manage.py reconcile_payment LOCAL_PAYMENT_ID VERIFIED_PROVIDER_ORDER_ID
```

The command stores that identity and replays previously authenticated transaction
events with the matching signed provider ID. Later callbacks use the same identity.
A confirmed successful payment becomes paid; a payment on an already cancelled
order is recorded and flagged for manual fulfillment/refund. Existing review notes
are preserved. Inspect the payment and order afterward; identity reconciliation
does not itself prove that funds were received.

If an old checkout cannot be identified, keep it reserved for manual review.
Before releasing stock or allowing another charge, independently confirm the
provider outcome and that the old checkout can no longer accept payment.

Schedule `python manage.py cancel_expired_orders` regularly (for example, every
minute) using the deployment scheduler. Orders expire after the configured payment
window plus grace period. Use PostgreSQL in deployment for row locking; SQLite is
for local checks only.
