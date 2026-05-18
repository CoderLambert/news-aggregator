from django.core.management.base import BaseCommand
from api.models import News
from api.services.vector_store import VectorStoreService


class Command(BaseCommand):
    help = '回填历史新闻的向量嵌入到ChromaDB'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='每批处理数量 (默认50)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='强制重新生成所有向量(包括已存在的)',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        force = options['force']

        vs = VectorStoreService()
        existing_ids = set() if force else vs.get_stored_ids()

        queryset = News.objects.all().order_by('id')
        total = queryset.count()
        if force:
            to_process = total
        else:
            to_process = total - len(existing_ids)

        self.stdout.write(f'总新闻数: {total}, 已有向量: {len(existing_ids)}, 待处理: {to_process}')

        if to_process == 0:
            self.stdout.write(self.style.SUCCESS('所有新闻已有向量，无需处理'))
            return

        processed = 0
        batch_ids = []
        batch_texts = []

        for news in queryset.iterator(chunk_size=200):
            if not force and news.id in existing_ids:
                continue

            text = news.title
            if news.content:
                text = news.title + ' ' + news.content[:500]

            batch_ids.append(news.id)
            batch_texts.append(text)

            if len(batch_ids) >= batch_size:
                vs.add_news_batch(batch_ids, batch_texts)
                processed += len(batch_ids)
                self.stdout.write(f'已处理: {processed}/{to_process}')
                batch_ids = []
                batch_texts = []

        if batch_ids:
            vs.add_news_batch(batch_ids, batch_texts)
            processed += len(batch_ids)

        self.stdout.write(self.style.SUCCESS(f'回填完成! 共处理 {processed} 条新闻'))
        self.stdout.write(f'ChromaDB中共有 {vs.count()} 条向量')
