from django.urls import path
from . import views

urlpatterns = [
    path('news/', views.NewsListView.as_view(), name='news-list'),
    path('news/<int:pk>/', views.NewsDetailView.as_view(), name='news-detail'),
    path('news/<int:pk>/chat/', views.NewsChatView.as_view(), name='news-chat'),
    path('news/<int:pk>/suggested-questions/', views.NewsSuggestedQuestionsView.as_view(), name='news-suggested-questions'),
    path('news/<int:pk>/fetch-full/', views.NewsFetchFullView.as_view(), name='news-fetch-full'),
    path('news/<int:pk>/translate/', views.NewsTranslateFullView.as_view(), name='news-translate'),
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
    # Auth
    path('auth/csrf/', views.csrf_token, name='auth-csrf'),
    path('auth/register/', views.auth_register, name='auth-register'),
    path('auth/login/', views.auth_login, name='auth-login'),
    path('auth/logout/', views.auth_logout, name='auth-logout'),
    path('auth/me/', views.auth_me, name='auth-me'),
]
