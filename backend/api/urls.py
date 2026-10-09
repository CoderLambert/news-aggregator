from django.urls import path
from . import views
from . import research_views
from . import subscription_views
from . import crawler_views
from . import search_index_views
from . import health_views

urlpatterns = [
    path('health/live/', health_views.health_live, name='health-live'),
    path('health/ready/', health_views.health_ready, name='health-ready'),
    path('admin/crawler/dashboard/', crawler_views.CrawlerDashboardView.as_view(), name='crawler-admin-dashboard'),
    path('admin/crawler/settings/', crawler_views.CrawlerSettingsView.as_view(), name='crawler-admin-settings'),
    path('admin/crawler/targets/', crawler_views.CrawlerTargetListView.as_view(), name='crawler-admin-targets'),
    path('admin/crawler/targets/<str:spider_name>/', crawler_views.CrawlerTargetDetailView.as_view(), name='crawler-admin-target-detail'),
    path('admin/crawler/batches/', crawler_views.CrawlBatchListCreateView.as_view(), name='crawler-admin-batches'),
    path('admin/crawler/batches/<uuid:batch_id>/', crawler_views.CrawlBatchDetailView.as_view(), name='crawler-admin-batch-detail'),
    path('admin/crawler/runs/<uuid:run_id>/', crawler_views.CrawlRunDetailView.as_view(), name='crawler-admin-run-detail'),
    path('admin/crawler/runs/<uuid:run_id>/cancel/', crawler_views.CrawlRunCancelView.as_view(), name='crawler-admin-run-cancel'),
    path('admin/crawler/runs/<uuid:run_id>/retry/', crawler_views.CrawlRunRetryView.as_view(), name='crawler-admin-run-retry'),
    path('admin/search-index/dashboard/', search_index_views.SearchIndexDashboardView.as_view(), name='search-index-admin-dashboard'),
    path('admin/search-index/settings/', search_index_views.SearchIndexSettingsView.as_view(), name='search-index-admin-settings'),
    path('admin/search-index/runs/', search_index_views.SearchIndexRunListCreateView.as_view(), name='search-index-admin-runs'),
    path('admin/search-index/runs/<uuid:run_id>/', search_index_views.SearchIndexRunDetailView.as_view(), name='search-index-admin-run-detail'),
    path('admin/search-index/runs/<uuid:run_id>/cancel/', search_index_views.SearchIndexRunCancelView.as_view(), name='search-index-admin-run-cancel'),
    path('chatgpt-subscription/', subscription_views.ChatGPTSubscriptionStatusView.as_view(), name='chatgpt-subscription-status'),
    path('chatgpt-subscription/connect/', subscription_views.ChatGPTSubscriptionConnectView.as_view(), name='chatgpt-subscription-connect'),
    path('chatgpt-subscription/handoff/', subscription_views.ChatGPTSubscriptionHandoffView.as_view(), name='chatgpt-subscription-handoff'),
    path('chatgpt-subscription/callback/', subscription_views.ChatGPTSubscriptionCallbackView.as_view(), name='chatgpt-subscription-callback'),
    path('chatgpt-subscription/attempts/<uuid:attempt_id>/', subscription_views.ChatGPTSubscriptionAttemptView.as_view(), name='chatgpt-subscription-attempt'),
    path('chatgpt-subscription/connections/<uuid:connection_id>/models/', subscription_views.ChatGPTSubscriptionModelsView.as_view(), name='chatgpt-subscription-models'),
    path('chatgpt-subscription/connections/<uuid:connection_id>/activate/', subscription_views.ChatGPTSubscriptionActivateView.as_view(), name='chatgpt-subscription-activate'),
    path('chatgpt-subscription/connections/<uuid:connection_id>/select-model/', subscription_views.ChatGPTSubscriptionSelectModelView.as_view(), name='chatgpt-subscription-select-model'),
    path('chatgpt-subscription/connections/<uuid:connection_id>/', subscription_views.ChatGPTSubscriptionDisconnectView.as_view(), name='chatgpt-subscription-disconnect'),
    path('news/', views.NewsListView.as_view(), name='news-list'),
    path('news/<int:pk>/', views.NewsDetailView.as_view(), name='news-detail'),
    path('news/<int:pk>/chat/', views.NewsChatView.as_view(), name='news-chat'),
    path('news/<int:pk>/suggested-questions/', views.NewsSuggestedQuestionsView.as_view(), name='news-suggested-questions'),
    path('news/<int:pk>/fetch-full/', views.NewsFetchFullView.as_view(), name='news-fetch-full'),
    path('news/<int:pk>/translate/', views.NewsTranslateFullView.as_view(), name='news-translate'),
    path('provider-comparisons/', views.ProviderComparisonListCreateView.as_view(), name='provider-comparison-list'),
    path('provider-comparisons/<int:pk>/', views.ProviderComparisonDetailView.as_view(), name='provider-comparison-detail'),
    path('provider-comparisons/<int:pk>/retest/', views.ProviderComparisonRetestView.as_view(), name='provider-comparison-retest'),
    path('news/<int:pk>/tts/', views.NewsTTSView.as_view(), name='news-tts'),
    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('sources/', views.SourceListView.as_view(), name='source-list'),
    # Favorites
    path('favorites/', views.FavoriteListView.as_view(), name='favorite-list'),
    path('favorites/<int:pk>/', views.FavoriteDestroyView.as_view(), name='favorite-destroy'),
    path('favorites/check/', views.FavoriteCheckView.as_view(), name='favorite-check'),
    # Blocked news
    path('blocked/', views.BlockedNewsListView.as_view(), name='blocked-list'),
    path('blocked/check/', views.BlockedNewsCheckView.as_view(), name='blocked-check'),
    # Research Agent
    path('research/', research_views.research_create, name='research-create'),
    path('research/sessions/', research_views.ResearchSessionListView.as_view(), name='research-session-list'),
    path('research/<uuid:pk>/', research_views.ResearchSessionDetailView.as_view(), name='research-session-detail'),
    path('research/<uuid:pk>/chat/', research_views.research_chat, name='research-chat'),
    path('research/<uuid:pk>/stream/', research_views.research_stream, name='research-stream'),
    path('research/<uuid:session_pk>/results/', research_views.ResearchSearchResultListView.as_view(), name='research-results'),
    # Auth
    path('auth/csrf/', views.csrf_token, name='auth-csrf'),
    path('auth/register/', views.auth_register, name='auth-register'),
    path('auth/login/', views.auth_login, name='auth-login'),
    path('auth/logout/', views.auth_logout, name='auth-logout'),
    path('auth/me/', views.auth_me, name='auth-me'),
]
