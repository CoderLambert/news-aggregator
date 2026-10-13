from django.urls import path
from . import smart_channel_views as views

urlpatterns = [
    path('me/channel-subscriptions/', views.SmartSubscriptionsView.as_view(), name='channel-subscriptions'),
    path('me/channel-groups/<int:pk>/', views.SmartGroupDetailView.as_view(), name='channel-group-detail'),
    path('smart-channels/catalog/', views.CatalogView.as_view(), name='smart-channel-catalog'),
    path('smart-channels/sources/<int:pk>/', views.SourceProfileView.as_view(), name='smart-channel-profile'),
    path('smart-channels/resolve/', views.ResolveChannelView.as_view(), name='smart-channel-resolve'),
    path('smart-channels/dashboard/', views.DashboardView.as_view(), name='smart-channel-dashboard'),
    path('me/smart-channels/settings/', views.GroupingConfigView.as_view(), name='smart-channel-settings'),
    path('me/smart-channels/proposals/', views.ProposalsView.as_view(), name='smart-channel-proposals'),
    path('me/smart-channels/proposals/<uuid:pk>/', views.ProposalView.as_view(), name='smart-channel-proposal'),
    path('me/smart-channels/proposals/<uuid:pk>/apply/', views.ApplyProposalView.as_view(), name='smart-channel-apply'),
    path('me/smart-channels/proposals/<uuid:pk>/cancel/', views.CancelProposalView.as_view(), name='smart-channel-cancel'),
    path('me/smart-channels/proposals/<uuid:pk>/undo/', views.UndoProposalView.as_view(), name='smart-channel-undo'),
    path('me/smart-channels/intake/', views.IntakeView.as_view(), name='smart-channel-intake'),
    path('me/reading-stats/', views.ReadingStatsView.as_view(), name='reading-stats'),
    path('admin/smart-channels/', views.SiteClassifierView.as_view(), name='smart-channel-admin'),
]
