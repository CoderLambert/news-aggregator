import json
import os
from pathlib import Path
import time
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Check the channel worker heartbeat without loading any model.'
    def handle(self, *args, **options):
        try:
            path = Path(os.environ['CHANNEL_WORKER_HEARTBEAT'])
            data = json.loads(path.read_text(encoding='utf-8'))
            age = time.time() - float(data['time'])
            if not 0 <= age < 180 or type(data['pid']) is not int or data['pid'] <= 0:
                raise ValueError()
            os.kill(data['pid'], 0)
        except (KeyError, OSError, ValueError, TypeError):
            raise CommandError('channel worker heartbeat is missing or stale') from None
        self.stdout.write('channel worker healthy')
