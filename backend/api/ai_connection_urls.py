"""Original T01 connection endpoints; no inference or worker endpoints."""
from django.urls import path
from api.ai_connection_views import (AIProviderCatalogView, UserAIConnectionListCreateView,
    UserAIConnectionDetailView, UserAIConnectionKeyView)

urlpatterns = [
    path('providers/', AIProviderCatalogView.as_view(), name='ai-provider-catalog'),
    path('connections/', UserAIConnectionListCreateView.as_view(), name='ai-connection-list'),
    path('connections/<uuid:connection_id>/', UserAIConnectionDetailView.as_view(), name='ai-connection-detail'),
    path('connections/<uuid:connection_id>/key/', UserAIConnectionKeyView.as_view(), name='ai-connection-key'),
]
