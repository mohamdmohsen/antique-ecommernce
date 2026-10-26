from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from order.models import Order
from payments.models import Payment, Refund


class Command(BaseCommand):
    help = 'Record an independently confirmed full refund without sending another provider request'

    def add_arguments(self, parser):
        parser.add_argument('payment_id', type=int)
        parser.add_argument('--provider-id', required=True)
        parser.add_argument('--amount-cents', required=True, type=int)
        parser.add_argument('--operator', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options['operator'], is_active=True, is_staff=True).first()
        if not actor or not actor.has_perm('payments.change_payment'):
            raise CommandError('A staff operator with payment change permission is required.')
        if not options['provider_id'].isdigit() or len(options['provider_id']) > 50:
            raise CommandError('Use the independently verified numeric refund transaction ID.')
        try:
            candidate = Payment.objects.get(pk=options['payment_id'])
        except Payment.DoesNotExist as exc:
            raise CommandError('Payment does not exist.') from exc
        Order.objects.select_for_update().get(pk=candidate.order_id)
        payment = Payment.objects.select_for_update().get(pk=candidate.pk)
        if options['amount_cents'] != payment.amount_cents:
            raise CommandError('Only confirmed full refunds can be recorded; partial refunds require manual accounting.')
        if payment.status not in {Payment.SUCCEEDED, Payment.REFUNDED}:
            raise CommandError('Only a successful payment can be reconciled as fully refunded.')
        refund, _ = Refund.objects.get_or_create(payment=payment, defaults={'amount_cents':payment.amount_cents})
        if refund.provider_id and refund.provider_id != options['provider_id']:
            raise CommandError('Existing provider ID differs; review without overwriting it.')
        refund.provider_id = options['provider_id']
        refund.status = Refund.SUCCEEDED
        refund.note = f'Full refund independently confirmed by {actor.username}.'
        refund.requested_by = refund.requested_by or actor
        refund.save(update_fields=['provider_id', 'status', 'note', 'requested_by'])
        payment.status = Payment.REFUNDED
        payment.save(update_fields=['status'])
        self.stdout.write(f'Payment {payment.pk}: full refund recorded. No provider request sent.')
