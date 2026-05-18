from django.urls import path
from . import views

urlpatterns = [
    path('news/', views.NewsListView.as_view(), name='news-list'),
    path('news/<int:pk>/', views.NewsDetailView.as_view(), name='news-detail'),
    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('sources/', views.SourceListView.as_view(), name='source-list'),
]
