from django.urls import path
from . import views

urlpatterns = [
    path('news/', views.NewsListView.as_view(), name='news-list'),
    path('news/<int:pk>/', views.NewsDetailView.as_view(), name='news-detail'),
    path('news/<int:pk>/chat/', views.NewsChatView.as_view(), name='news-chat'),
    path('news/<int:pk>/suggested-questions/', views.NewsSuggestedQuestionsView.as_view(), name='news-suggested-questions'),
    path('news/<int:pk>/fetch-full/', views.NewsFetchFullView.as_view(), name='news-fetch-full'),
    path('news/<int:pk>/translate/', views.NewsTranslateFullView.as_view(), name='news-translate'),
    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('sources/', views.SourceListView.as_view(), name='source-list'),
]
