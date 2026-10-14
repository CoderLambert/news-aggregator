"""Regression coverage: deleting a channel must never erase article/user history."""
import pytest
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone

from api.models import BlockedNews, Category, ChannelSubscription, ChatSession, Favorite, News, Source


@pytest.mark.django_db
def test_source_and_category_delete_are_protected_by_articles(client):
    user = get_user_model().objects.create_superuser('preserve-history-admin', 'admin@example.com', 'password123')
    source = Source.objects.create(name='Persistent Publisher', url='https://publisher.example')
    category = Category.objects.create(name='Permanent Category', slug='permanent-category')
    news = News.objects.create(title='Retain my reading history', content='summary',
                               url='https://publisher.example/story', publish_time=timezone.now(),
                               source=source, category=category)
    favorite = Favorite.objects.create(user=user, news=news, type='bookmark')
    block = BlockedNews.objects.create(user=user, news=news)
    conversation = ChatSession.objects.create(user=user, news=news)
    subscription = ChannelSubscription.objects.create(user=user, source=source)

    for obj in (source, category):
        with pytest.raises(ProtectedError):
            obj.delete()
        with pytest.raises(ProtectedError):
            obj.__class__.objects.filter(pk=obj.pk).delete()

    client.force_login(user)
    for kind, pk in (('source', source.pk), ('category', category.pk)):
        url = reverse(f'admin:api_{kind}_delete', args=[pk])
        response = client.get(url)
        assert response.status_code == 200
        # Admin's protected-object confirmation page must not offer a destructive POST.
        assert response.context['perms_lacking'] == set()
        assert response.context['protected']
    assert News.objects.filter(pk=news.pk).exists()
    assert Favorite.objects.filter(pk=favorite.pk).exists()
    assert BlockedNews.objects.filter(pk=block.pk).exists()
    assert ChatSession.objects.filter(pk=conversation.pk).exists()
    assert ChannelSubscription.objects.filter(pk=subscription.pk).exists()


@pytest.mark.django_db
def test_source_with_only_personal_subscriptions_is_protected():
    user = get_user_model().objects.create_user('subscriber-only', password='password123')
    source = Source.objects.create(name='Subscription Only', url='https://newsletter.example')
    ChannelSubscription.objects.create(user=user, source=source)
    with pytest.raises(ProtectedError):
        Source.objects.filter(pk=source.pk).delete()
    assert ChannelSubscription.objects.filter(user=user, source=source).exists()


@pytest.mark.django_db
def test_unreferenced_source_and_category_can_still_be_deleted():
    source = Source.objects.create(name='Unused Source', url='https://unused.example')
    category = Category.objects.create(name='Unused Category', slug='unused-category')
    source.delete()
    category.delete()
    assert not Source.objects.filter(pk=source.pk).exists()
    assert not Category.objects.filter(pk=category.pk).exists()
