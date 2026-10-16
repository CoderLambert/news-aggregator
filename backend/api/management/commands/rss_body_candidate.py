"""Explicit local resolution of a suspicious body; never fetches source content."""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from api.models import BodyCandidate
from api.rss.content_store import resolve_candidate


class Command(BaseCommand):
    help = 'Inspect or explicitly accept/reject one quarantined RSS body candidate.'

    def add_arguments(self, parser):
        parser.add_argument('candidate_id')
        parser.add_argument('decision', choices=['accept', 'reject'])
        parser.add_argument('--execute', action='store_true')

    def handle(self, *args, **options):
        try:
            candidate = BodyCandidate.objects.get(pk=options['candidate_id'])
        except (BodyCandidate.DoesNotExist, ValueError, ValidationError):
            raise CommandError('candidate_missing') from None
        if not options['execute']:
            self.stdout.write(f'dry-run candidate={candidate.pk} state={candidate.state} hash={candidate.canonical_hash} decision={options["decision"]}')
            return
        result = resolve_candidate(candidate.pk, decision=options['decision'])
        self.stdout.write(f'{result.status}: {result.reason or "ok"}')
        if result.status not in {'accepted', 'unchanged', 'rejected'}:
            raise CommandError(result.reason)
