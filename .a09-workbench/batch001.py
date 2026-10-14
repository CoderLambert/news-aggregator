# NH-16: apply model, route and caller changes to the reviewed baseline.
P.replace('backend/api/smart_channel_models.py',
    "    status = models.CharField(max_length=16, default='pending')\n    created_at = models.DateTimeField(auto_now_add=True)",
    "    status = models.CharField(max_length=16, default='pending')\n    review_reason = models.CharField(max_length=500, blank=True, default='')\n    reviewed_at = models.DateTimeField(null=True, blank=True)\n    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,\n        on_delete=models.SET_NULL, related_name='reviewed_channel_intakes')\n    created_at = models.DateTimeField(auto_now_add=True)")
P.replace('backend/api/smart_channel_views.py',
    'from api.services.channel_topics import TOPICS, PRESETS, TOPIC_MAP, channel_articles, profile_data, base_profile',
    'from api.services.channel_topics import TOPICS, PRESETS, TOPIC_MAP, channel_articles, profile_data, base_profile\nfrom api.services.channel_intake import normalize_intake_url, intake_data, submit_intake')
P.region('backend/api/smart_channel_views.py', 'def normalize_url(value):', 'class ResolveChannelView(PrivateWorkspaceView):',
    'def normalize_url(value):\n    return normalize_intake_url(value)\n\n\n')
P.region('backend/api/smart_channel_views.py', 'class IntakeView(PrivateWorkspaceView):', 'class GroupingConfigView(PrivateWorkspaceView):',
    '''class IntakeView(PrivateWorkspaceView):
    def get(self, request):
        return Response([intake_data(item) for item in ChannelIntakeRequest.objects.filter(
            user=request.user).order_by('-created_at', '-pk')[:30]])

    def post(self, request):
        item, created = submit_intake(request.user, request.data.get('url'))
        return Response(intake_data(item), status=201 if created else 200)


''')
P.replace('backend/api/smart_channel_views.py',
    "'intake_requests': list(ChannelIntakeRequest.objects.order_by('-created_at').values('id', 'url', 'status', 'created_at')[:30])",
    "'intake_requests': [intake_data(item) for item in ChannelIntakeRequest.objects.order_by('-created_at', '-pk')[:30]]")
P.replace('backend/api/smart_channel_urls.py', 'urlpatterns = [',
    "from .channel_intake_views import IntakeHistoryView, AdminIntakeHistoryView, IntakeReviewView\n\nurlpatterns = [\n    path('me/smart-channels/intake/history/', IntakeHistoryView.as_view(), name='smart-channel-intake-history'),\n    path('admin/smart-channels/intake/', AdminIntakeHistoryView.as_view(), name='smart-channel-intake-admin-list'),\n    path('admin/smart-channels/intake/<int:pk>/', IntakeReviewView.as_view(), name='smart-channel-intake-review'),")
P.replace('frontend/src/pages/ChannelWorkspace.tsx',
    "import AddChannelDialog from '@/components/workspace/AddChannelDialog'",
    "import AddChannelDialog from '@/components/workspace/AddChannelDialog'\nimport ChannelIntakePanel from '@/components/workspace/ChannelIntakePanel'")
P.replace('frontend/src/pages/ChannelWorkspace.tsx',
    '    {login && <AuthModal onClose={() => setLogin(false)} />}',
    '    {user && config.enabled && <ChannelIntakePanel key={user.id} viewer={user.id} />}\n    {login && <AuthModal onClose={() => setLogin(false)} />}')
P.replace('frontend/src/pages/SmartGroupingWorkspace.tsx',
    "import WorkspaceModal from '@/components/workspace/WorkspaceModal'",
    "import WorkspaceModal from '@/components/workspace/WorkspaceModal'\nimport ChannelIntakePanel from '@/components/workspace/ChannelIntakePanel'")
P.replace('frontend/src/pages/SmartGroupingWorkspace.tsx',
    '<h3>待接入申请</h3><p className="workspace-caption">这些地址未启用抓取；需另行核验官方 API/RSS 并登记采集策略。</p><ul className="workspace-intake-list">{data.data.intake_requests.map(item => <li key={item.id}><code>{item.url}</code><span>{item.status === \'pending\' ? \'待审核接入\' : item.status}</span></li>)}</ul>',
    '<ChannelIntakePanel viewer={viewer} admin />')
P.replace('frontend/src/components/workspace/AddChannelDialog.tsx',
    "  const intake = useMutation({ mutationFn: (value: string) => workspaceRequest('/me/smart-channels/intake/', { method: 'POST', body: { url: value } }) })",
    "  const intake = useMutation({ mutationFn: (value: string) => workspaceRequest('/me/smart-channels/intake/', { method: 'POST', body: { url: value } }), onSuccess: () => { void client.invalidateQueries({ queryKey: workspaceKeys.all }) } })")
