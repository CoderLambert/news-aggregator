from django.core.management.base import BaseCommand

from api.services.tts_service import clean_expired_cache


class Command(BaseCommand):
    help = 'Remove TTS cache files not accessed in the last 3 days'

    def handle(self, *args, **options):
        removed, freed = clean_expired_cache()
        if removed:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleaned {removed} expired TTS cache file(s), freed {freed / 1024 / 1024:.1f} MB'
                )
            )
        else:
            self.stdout.write('No expired TTS cache files to clean')
