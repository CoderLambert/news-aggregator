"""Local directory lookup with current personal state, never network discovery."""
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from api.rss.access import authorized_news, authorized_sources, news_in_sources
from api.rss.directory import DirectoryCursorError, DirectoryValidationError, search_directory
from api.rss.http import RssAPIView
from api.rss.models import SourceFeedLink
from api.rss.subscriptions import engine_identity, EngineUnavailable


class DirectoryView(RssAPIView):
    personal = False

    def get(self, request):
        try:
            data = search_directory(request.query_params.get('q', ''),
                limit=int(request.query_params.get('limit', '20')), cursor=request.query_params.get('cursor'),
                category=request.query_params.get('category', ''))
        except (DirectoryCursorError, DirectoryValidationError, ValueError):
            raise ValidationError('目录查询无效或已过期，请重新搜索。') from None
        try:
            instance, account = engine_identity()
        except EngineUnavailable:
            instance, account = None, None
        for row in data['results']:
            row['executable'] = row['kind'] == 'feed' and not row['required_parameters'] and not row['capability_requirements'] and instance is not None
            links = SourceFeedLink.objects.filter(binding__canonical_feed_url=row['public_url'],
                binding__engine_instance_uuid=instance, binding__account_id=account,
                association_policy={'version': 1, 'mode': 'all'}, source_id__in=authorized_sources(request.user).values('pk'))
            row['subscribed'] = request.user.is_authenticated and links.filter(source__channel_subscriptions__user=request.user).exists()
            visible = authorized_sources(request.user).filter(feed_links__in=links)
            articles = news_in_sources(authorized_news(request.user), visible).order_by('-publish_time', '-pk')[:3]
            row['cached_articles'] = [{'id': article.pk, 'title': article.title, 'publish_time': article.publish_time} for article in articles]
        return Response(data)
