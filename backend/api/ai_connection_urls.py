"""Original T01 connection endpoints; no inference or worker endpoints."""
from django.urls import path
from api.ai_connection_views import (AIProviderCatalogView, UserAIConnectionListCreateView,
    UserAIConnectionDetailView, UserAIConnectionKeyView)
from api.ai_model_views import (AIModelCatalogView, AIModelListCreateView,
    AIModelDetailView, AIModelProbeView, AIModelAttemptListView)
from api.ai_preference_views import AITaskPreferencesView
from api.ai_usage_views import AIUsageView

urlpatterns = [
    path('usage/', AIUsageView.as_view(), name='ai-usage'),
    path('providers/', AIProviderCatalogView.as_view(), name='ai-provider-catalog'),
    path('task-preferences/', AITaskPreferencesView.as_view(), name='ai-task-preferences'),
    path('connections/', UserAIConnectionListCreateView.as_view(), name='ai-connection-list'),
    path('connections/<uuid:connection_id>/', UserAIConnectionDetailView.as_view(), name='ai-connection-detail'),
    path('connections/<uuid:connection_id>/key/', UserAIConnectionKeyView.as_view(), name='ai-connection-key'),
    path('connections/<uuid:connection_id>/model-catalog/', AIModelCatalogView.as_view(), name='ai-model-catalog'),
    path('connections/<uuid:connection_id>/models/', AIModelListCreateView.as_view(), name='ai-model-list'),
    path('connections/<uuid:connection_id>/models/<uuid:model_id>/', AIModelDetailView.as_view(), name='ai-model-detail'),
    path('connections/<uuid:connection_id>/models/<uuid:model_id>/probe/', AIModelProbeView.as_view(), name='ai-model-probe'),
    path('connections/<uuid:connection_id>/models/<uuid:model_id>/attempts/', AIModelAttemptListView.as_view(), name='ai-model-attempt-list'),
]
