"""API routes precede the static single-page application fallback."""
from django.urls import path, include, re_path
from django.views.static import serve
from django.conf import settings

urlpatterns = [
    path('api/me/ai/', include('api.ai_connection_urls')),
    path('api/', include('api.smart_channel_urls')),
    path('api/', include('api.urls')),
    re_path(r'^assets/(?P<path>.*)$', serve, {'document_root': settings.FRONTEND_DIR / 'assets'}),
    re_path(r'^(favicon\.svg|icons\.svg)$', serve, {'document_root': settings.FRONTEND_DIR}, name='frontend-root-static'),
    re_path(r'^(?!api/|assets/).+$', serve, {'path': 'index.html', 'document_root': settings.FRONTEND_DIR}),
    path('', serve, {'path': 'index.html', 'document_root': settings.FRONTEND_DIR}),
]
