from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import EmailValidator

from api.models import SignupInvite
from api.services.account_security import issue_signup_invite, normalize_email


class Command(BaseCommand):
    help = 'Create a one-use signup invitation and print its token once.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--expires-hours', type=int, default=24)

    def handle(self, *args, **options):
        email = options['email']
        expires_hours = options['expires_hours']
        if not 1 <= expires_hours <= 168:
            raise CommandError('--expires-hours must be an integer from 1 to 168.')

        try:
            normalized_email = normalize_email(email)
            if len(normalized_email) > SignupInvite._meta.get_field('email').max_length:
                raise ValidationError('email is too long')
            EmailValidator()(normalized_email)
        except (TypeError, ValidationError) as error:
            raise CommandError('--email must be a valid email address.') from error

        token = issue_signup_invite(normalized_email, expires_hours)
        self.stdout.write(token)
