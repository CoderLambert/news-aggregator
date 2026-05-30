"""Management command to check network connectivity to translation services."""

from django.core.management.base import BaseCommand
import socket
import urllib.request
import ssl


TRANSLATION_ENDPOINTS = [
    ('translate.google.com', 443, 'Google Translate'),
    ('translate.googleapis.com', 443, 'Google Translate API'),
    ('api.mymemory.translated.net', 443, 'MyMemory'),
    ('8.8.8.8', 53, 'DNS (Google)'),
]


class Command(BaseCommand):
    help = 'Check network connectivity to translation services'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json', action='store_true',
            help='Output results in JSON format for script consumption',
        )

    def handle(self, *args, **options):
        use_json = options['json']
        results = []

        # Test DNS resolution first
        dns_ok = False
        try:
            socket.getaddrinfo('translate.google.com', 443)
            dns_ok = True
        except Exception as e:
            if not use_json:
                self.stdout.write(f'  DNS resolution failed: {e}')

        # Test TCP connectivity to each endpoint
        for host, port, label in TRANSLATION_ENDPOINTS:
            try:
                sock = socket.create_connection((host, port), timeout=5)
                sock.close()
                status = 'ok'
                error = ''
                if not use_json:
                    self.stdout.write(f'  ✓ {label} ({host}:{port}) - OK')
            except Exception as e:
                status = 'failed'
                error = str(e)
                if not use_json:
                    self.stdout.write(self.style.ERROR(
                        f'  ✗ {label} ({host}:{port}) - {e}'
                    ))

            results.append({
                'host': host,
                'port': port,
                'label': label,
                'status': status,
                'error': error,
            })

        # Test actual translation via HTTP
        translation_ok = False
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                'https://translate.google.com/m?sl=en&tl=zh-CN&q=hello',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                if resp.status == 200:
                    translation_ok = True
                    if not use_json:
                        self.stdout.write('  ✓ HTTP translation test - OK')
        except Exception as e:
            if not use_json:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ HTTP translation test - {e}'
                ))

        overall = 'ok' if translation_ok else 'failed'
        if not use_json:
            self.stdout.write(self.style.SUCCESS(
                f'\nOverall: {"OK - translation service is reachable" if translation_ok else "FAILED - translation service is unreachable"}'
            ))
        else:
            import json
            output = {
                'dns_ok': dns_ok,
                'translation_ok': translation_ok,
                'overall': overall,
                'endpoints': results,
            }
            self.stdout.write(json.dumps(output))

        # Return exit code based on status
        import sys
        if not translation_ok:
            sys.exit(1)
