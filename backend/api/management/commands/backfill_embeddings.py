from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '兼容入口：排队同步历史新闻向量；使用 --force 时进行版本化重建'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=100, help='兼容参数；批大小由索引设置控制')
        parser.add_argument('--force', action='store_true', default=False, help='构建并切换完整的新索引')

    def handle(self, *args, **options):
        args = ['--wait']
        if options['force']:
            args.append('--rebuild')
        call_command('sync_embeddings', *args)
