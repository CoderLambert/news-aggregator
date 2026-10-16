"""Personal read state, independent of daily reading analytics and engine state."""
from django.conf import settings
from django.db import models


class NewsReadState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='news_read_states')
    news = models.ForeignKey('api.News', on_delete=models.CASCADE, related_name='read_states')
    is_read = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'news'], name='rss_personal_news_read_state')]
