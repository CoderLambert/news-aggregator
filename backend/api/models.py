import uuid

from django.db import models


def generate_chatgpt_host_id():
    return f'urn:uuid:{uuid.uuid4()}'


class Category(models.Model):
    name = models.CharField('分类名称', max_length=100, unique=True)
    slug = models.SlugField('slug', max_length=100, unique=True)
    description = models.TextField('描述', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '分类'
        verbose_name_plural = '分类'
        ordering = ['name']

    def __str__(self):
        return self.name


class Source(models.Model):
    TYPE_CHOICES = [
        ('news', '新闻媒体'),
        ('aggregator', '聚合平台'),
        ('discussion', '讨论社区'),
    ]
    name = models.CharField('来源名称', max_length=100, unique=True)
    url = models.URLField('来源网址', max_length=255)
    logo = models.URLField('Logo', max_length=255, blank=True, default='')
    country = models.CharField('国家', max_length=50, default='CN')
    language = models.CharField('语言', max_length=50, default='zh')
    source_type = models.CharField('类型', max_length=20, choices=TYPE_CHOICES, default='news')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '新闻源'
        verbose_name_plural = '新闻源'
        ordering = ['name']

    def __str__(self):
        return self.name


class News(models.Model):
    title = models.CharField('标题', max_length=500, db_index=True)
    content = models.TextField('内容')
    title_zh = models.TextField('中文标题', blank=True, default='')
    content_zh = models.TextField('中文内容', blank=True, default='')
    author = models.CharField('作者', max_length=100, blank=True, default='')
    publish_time = models.DateTimeField('发布时间', db_index=True)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, verbose_name='来源')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name='分类')
    url = models.URLField('原文链接', max_length=500, unique=True, db_index=True)
    cover_image = models.URLField('封面图', max_length=500, blank=True, default='')
    title_hash = models.BigIntegerField('标题哈希', null=True, blank=True, db_index=True)
    related_to = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, verbose_name='关联主新闻')
    created_at = models.DateTimeField('入库时间', auto_now_add=True)

    # Translation tracking
    TRANSLATION_STATUS_CHOICES = [
        ('pending', '等待翻译'),
        ('translating', '翻译中'),
        ('success', '翻译成功'),
        ('failed', '翻译失败'),
        ('network_error', '网络错误'),
    ]
    translation_status = models.CharField(
        '翻译状态', max_length=20, choices=TRANSLATION_STATUS_CHOICES,
        default='pending', db_index=True,
    )
    translation_error = models.TextField('翻译错误信息', blank=True, default='')
    translation_retry_count = models.PositiveIntegerField('重试次数', default=0)
    last_translation_attempt = models.DateTimeField('最后翻译时间', null=True, blank=True)

    # Full article content (fetched via real article fetcher providers)
    full_content = models.TextField('完整原文(Markdown)', blank=True, default='')
    full_content_fetched_at = models.DateTimeField('原文获取时间', null=True, blank=True)
    full_content_zh = models.TextField('完整原文(中文)', blank=True, default='')
    full_content_zh_fetched_at = models.DateTimeField('中文翻译时间', null=True, blank=True)

    FULL_CONTENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('fetching', 'Fetching'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('network_error', 'Network Error'),
        ('validation_failed', 'Validation Failed'),
    ]
    full_content_fetch_status = models.CharField(
        '全文抓取状态',
        max_length=32,
        choices=FULL_CONTENT_STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    full_content_fetch_error = models.TextField('全文抓取错误信息', blank=True, default='')
    full_content_fetch_provider = models.CharField('全文抓取 Provider', max_length=64, blank=True, default='')
    full_content_quality_score = models.FloatField('全文质量分', null=True, blank=True)
    full_content_retry_count = models.PositiveIntegerField('全文抓取重试次数', default=0)
    last_full_content_attempt = models.DateTimeField('最后全文抓取时间', null=True, blank=True)
    full_content_backfill_source = models.CharField('Scrapy 回填来源', max_length=64, blank=True, default='')
    full_content_backfill_at = models.DateTimeField('Scrapy 回填时间', null=True, blank=True)

    # LLM-generated suggested questions (cached per article)
    suggested_questions = models.JSONField('AI 推荐问题', default=list, blank=True)
    suggested_questions_generated_at = models.DateTimeField('推荐问题生成时间', null=True, blank=True)

    class Meta:
        verbose_name = '新闻'
        verbose_name_plural = '新闻'
        ordering = ['-publish_time']
        indexes = [
            models.Index(fields=['-publish_time']),
            models.Index(fields=['title']),
        ]

    def __str__(self):
        return self.title


class ChatSession(models.Model):
    """Stores chat history for a specific news article."""
    news = models.OneToOneField(News, on_delete=models.CASCADE, related_name='chat_session')
    messages = models.JSONField('对话记录', default=list, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '对话会话'
        verbose_name_plural = '对话会话'

    def __str__(self):
        return f"Chat for {self.news.title[:20]}"


class UserNewsChatSession(models.Model):
    """Private article chat history for one signed-in website user."""

    user = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE, related_name='private_news_chats',
    )
    news = models.ForeignKey(
        News, on_delete=models.CASCADE, related_name='private_chat_sessions',
    )
    messages = models.JSONField('对话记录', default=list, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'news'], name='unique_user_news_chat'),
        ]
        verbose_name = '用户私有文章问答'
        verbose_name_plural = '用户私有文章问答'


class Favorite(models.Model):
    """User likes and bookmarks on news articles."""
    TYPE_CHOICES = [
        ('like', '点赞'),
        ('bookmark', '收藏'),
    ]
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='favorites')
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='favorited_by')
    type = models.CharField('类型', max_length=10, choices=TYPE_CHOICES)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '收藏'
        verbose_name_plural = '收藏'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'news', 'type'],
                name='unique_user_news_type',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} {self.type}d {self.news.title[:30]}"


class BlockedNews(models.Model):
    """User-blocked news — hidden from their feed."""
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='blocked_news')
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='blocked_by')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '屏蔽'
        verbose_name_plural = '屏蔽'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'news'],
                name='unique_user_blocked_news',
            ),
        ]

    def __str__(self):
        return f'{self.user.username} blocked {self.news.title[:30]}'


class ResearchSession(models.Model):
    """A multi-turn research conversation with the intelligent news agent.

    Stores the full OpenAI-format message history including tool_calls and
    tool role messages, enabling session persistence and resumption.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='research_sessions', null=True, blank=True, verbose_name='用户')
    title = models.CharField('会话标题', max_length=200, blank=True, default='')
    messages = models.JSONField('对话记录', default=list, blank=True)
    is_archived = models.BooleanField('已归档', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '研究会话'
        verbose_name_plural = '研究会话'
        ordering = ['-updated_at']

    def __str__(self):
        return self.title or str(self.id)[:8]


class ResearchSearchResult(models.Model):
    """Persistent record of each tool execution result within a research session.

    Stores both the full result JSON and extracted summary fields for fast
    querying and frontend display without parsing the message history.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        ResearchSession, on_delete=models.CASCADE,
        related_name='search_results', verbose_name='研究会话',
    )
    tool_name = models.CharField('工具名称', max_length=50)
    query = models.CharField('搜索查询', max_length=500, blank=True, default='')
    result_data = models.JSONField('结果数据', default=dict, blank=True)
    # Extracted summary fields for fast querying / display
    result_type = models.CharField('结果类型', max_length=20, db_index=True)
    source = models.CharField('来源', max_length=100, blank=True, default='')
    title = models.CharField('标题', max_length=500, blank=True, default='')
    url = models.URLField('链接', max_length=2000, blank=True, default='')
    hit_count = models.PositiveIntegerField('结果数量', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '搜索结果'
        verbose_name_plural = '搜索结果'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'result_type'], name='idx_result_session_type'),
            models.Index(fields=['session', 'created_at'], name='idx_result_session_created'),
        ]

    def __str__(self):
        return f'{self.tool_name}: {self.query[:30] or self.title[:30]}'


class ProviderComparison(models.Model):
    """One provider's result inside a provider-comparison run.

    This model is intentionally independent from News.full_content: comparison
    runs persist what each provider really returned for diagnostics/UI display,
    but never mutate the article cache used by readers.
    """

    run_id = models.UUIDField('对比运行 ID', db_index=True)
    news = models.ForeignKey(
        News,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='provider_comparisons',
        verbose_name='新闻',
    )
    url = models.URLField('原文链接', max_length=500, db_index=True)
    expected_title = models.CharField('期望标题', max_length=500, blank=True, default='')
    summary = models.TextField('摘要', blank=True, default='')
    provider = models.CharField('Provider', max_length=64, db_index=True)
    ok = models.BooleanField('是否成功', default=False, db_index=True)
    title = models.CharField('抓取标题', max_length=500, blank=True, default='')
    canonical_url = models.URLField('Canonical URL', max_length=500, blank=True, default='')
    markdown = models.TextField('Provider 返回 Markdown', blank=True, default='')
    quality_score = models.FloatField('质量分', null=True, blank=True)
    error = models.TextField('错误信息', blank=True, default='')
    validation_reasons = models.JSONField('校验失败原因', default=list, blank=True)
    content_length = models.PositiveIntegerField('内容长度', default=0)
    extractor = models.CharField('Extractor', max_length=128, blank=True, default='')
    metadata = models.JSONField('Provider 元数据', default=dict, blank=True)
    elapsed_ms = models.PositiveIntegerField('耗时(ms)', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Provider 对比结果'
        verbose_name_plural = 'Provider 对比结果'
        ordering = ['-created_at', 'provider']
        indexes = [
            models.Index(fields=['run_id', 'provider']),
            models.Index(fields=['url', '-created_at']),
        ]

    def __str__(self):
        return f'{self.provider} {"ok" if self.ok else "failed"} {self.url}'


class ChatGPTOAuthHost(models.Model):
    """Stable, opaque OAuth host identity for one deployment."""

    deployment_hash = models.CharField(max_length=64, unique=True)
    host_id = models.CharField(max_length=64, unique=True, default=generate_chatgpt_host_id)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ChatGPT OAuth 主机'
        verbose_name_plural = 'ChatGPT OAuth 主机'


class ChatGPTSubscriptionSelection(models.Model):
    """Monotonic user-level fence for subscription selection changes."""

    user = models.OneToOneField(
        'auth.User', primary_key=True, on_delete=models.CASCADE,
        related_name='chatgpt_subscription_selection',
    )
    generation = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ChatGPT 订阅选择状态'
        verbose_name_plural = 'ChatGPT 订阅选择状态'


class ChatGPTSubscriptionConnection(models.Model):
    """One user's encrypted, replaceable ChatGPT subscription credential set."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE, related_name='chatgpt_connections',
    )
    subject_hash = models.CharField(max_length=64)
    issuer = models.CharField(max_length=255)
    issued_client_id = models.CharField(max_length=255)
    # Existing registrations remain local; never silently relabel them as hosted.
    oauth_mode = models.CharField(max_length=16, default='local', db_index=True)
    registration_key_hash = models.CharField(max_length=64)
    encrypted_subject = models.TextField(blank=True, default='')
    granted_scopes = models.JSONField(default=list)
    account_name = models.CharField(max_length=255, blank=True, default='')
    account_email = models.EmailField(blank=True, default='')
    encrypted_access_token = models.TextField(blank=True, default='')
    encrypted_refresh_token = models.TextField(blank=True, default='')
    encrypted_id_token = models.TextField(blank=True, default='')
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    selected_model = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=False, db_index=True)
    needs_reauth = models.BooleanField(default=False, db_index=True)
    generation = models.PositiveIntegerField(default=0)
    credential_generation = models.PositiveIntegerField(default=0)
    auth_attempt_generation = models.PositiveIntegerField(default=0)
    refresh_lease_id = models.CharField(max_length=64, blank=True, default='')
    refresh_lease_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ChatGPT 订阅连接'
        verbose_name_plural = 'ChatGPT 订阅连接'
        constraints = [
            models.UniqueConstraint(fields=['user', 'registration_key_hash'], name='unique_chatgpt_user_registration'),
            models.UniqueConstraint(
                fields=['user'], condition=models.Q(is_active=True),
                name='one_active_chatgpt_connection_per_user',
            ),
        ]
        ordering = ['-updated_at']

    @property
    def connected(self):
        return bool(self.encrypted_access_token and self.encrypted_refresh_token and not self.needs_reauth)


class ChatGPTAuthAttempt(models.Model):
    """Short-lived, one-use OAuth state and encrypted PKCE verifier."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='chatgpt_auth_attempts')
    target_connection = models.ForeignKey(
        ChatGPTSubscriptionConnection, null=True, blank=True, on_delete=models.SET_NULL,
    )
    result_connection = models.ForeignKey(
        ChatGPTSubscriptionConnection, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='completed_auth_attempts',
    )
    state_hash = models.CharField(max_length=64, unique=True)
    nonce_hash = models.CharField(max_length=64)
    encrypted_pkce_verifier = models.TextField()
    encrypted_authorization_url = models.TextField()
    handoff_token_hash = models.CharField(max_length=64)
    browser_binding_hash = models.CharField(max_length=64, blank=True, default='')
    session_binding_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    handoff_origin = models.CharField(max_length=255, blank=True, default='')
    requested_client_id = models.CharField(max_length=255)
    # Freeze authorization settings so a deployment switch cannot redeem a
    # callback under a different client/redirect/token-auth contract.
    oauth_mode = models.CharField(max_length=16, default='local')
    redirect_uri = models.CharField(max_length=512, blank=True, default='')
    token_auth_method = models.CharField(max_length=32, default='none')
    requested_scopes = models.TextField(blank=True, default='')
    oauth_resource = models.CharField(max_length=255, blank=True, default='')
    target_attempt_generation = models.PositiveIntegerField(default=0)
    selection_connection_id_at_start = models.UUIDField(null=True, blank=True)
    selection_generation_at_start = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=16, default='pending', db_index=True)
    status_message = models.CharField(max_length=255, blank=True, default='')
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'ChatGPT OAuth 登录尝试'
        verbose_name_plural = 'ChatGPT OAuth 登录尝试'


class ChatGPTArticleTranslation(models.Model):
    """A completed full-text translation private to a user and connection."""

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='chatgpt_translations')
    connection = models.ForeignKey(
        ChatGPTSubscriptionConnection, on_delete=models.CASCADE, related_name='translations',
    )
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='chatgpt_translations')
    source_hash = models.CharField(max_length=64)
    model_slug = models.CharField(max_length=255)
    content = models.TextField()
    completed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ChatGPT 全文翻译'
        verbose_name_plural = 'ChatGPT 全文翻译'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'connection', 'news'], name='unique_chatgpt_news_translation',
            ),
        ]


class SharedArticleTranslation(models.Model):
    """Completed public article output, independent of users and credentials."""

    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='shared_translations')
    source_hash = models.CharField(max_length=64)
    target_language = models.CharField(max_length=16, default='zh-CN')
    translation_version = models.CharField(max_length=32)
    content = models.TextField()
    provider = models.CharField(max_length=32)
    model_slug = models.CharField(max_length=255, blank=True, default='')
    completed_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['news', 'source_hash', 'target_language', 'translation_version'],
            name='unique_shared_article_translation',
        )]


class SharedArticleTranslationTask(models.Model):
    """Cross-process coordination only; neither private output nor credentials."""

    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='shared_translation_tasks')
    source_hash = models.CharField(max_length=64)
    target_language = models.CharField(max_length=16, default='zh-CN')
    translation_version = models.CharField(max_length=32)
    status = models.CharField(max_length=16, default='idle')
    lease_token = models.UUIDField(default=uuid.uuid4)
    expires_at = models.DateTimeField(null=True)
    started_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['news', 'source_hash', 'target_language', 'translation_version'],
            name='unique_shared_article_task',
        )]


class CrawlerSettings(models.Model):
    """Singleton scheduler configuration and worker liveness snapshot."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    scheduler_enabled = models.BooleanField(default=True)
    interval_seconds = models.PositiveIntegerField(default=3600)
    run_on_worker_start = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    worker_heartbeat_at = models.DateTimeField(null=True, blank=True)
    worker_instance_id = models.CharField(max_length=128, blank=True, default='')
    updated_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='crawler_settings_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '爬虫调度设置'
        verbose_name_plural = '爬虫调度设置'


class CrawlerTarget(models.Model):
    """One server-registered spider exposed to the crawler control plane."""

    spider_name = models.CharField(primary_key=True, max_length=64)
    display_name = models.CharField(max_length=128)
    enabled = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    last_status = models.CharField(max_length=32, blank=True, default='')
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_items = models.PositiveIntegerField(default=0)
    last_responses = models.PositiveIntegerField(default=0)
    last_errors = models.PositiveIntegerField(default=0)
    last_safe_error = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['sort_order', 'spider_name']
        verbose_name = '爬虫来源'
        verbose_name_plural = '爬虫来源'


class CrawlBatch(models.Model):
    TRIGGER_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('startup', 'Startup'),
        ('manual', 'Manual'),
        ('retry', 'Retry'),
    ]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='queued', db_index=True)
    requested_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='requested_crawl_batches',
    )
    queued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    cancelled = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-queued_at']
        verbose_name = '抓取批次'
        verbose_name_plural = '抓取批次'


class CrawlRun(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancel_requested', 'Cancel requested'),
        ('cancelled', 'Cancelled'),
        ('skipped', 'Skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(CrawlBatch, on_delete=models.CASCADE, related_name='runs')
    target = models.ForeignKey(CrawlerTarget, on_delete=models.PROTECT, related_name='runs')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='queued', db_index=True)
    requested_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='requested_crawl_runs',
    )
    queued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    items = models.PositiveIntegerField(default=0)
    responses = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    http_statuses = models.JSONField(default=dict, blank=True)
    stats = models.JSONField(default=dict, blank=True)
    safe_error = models.CharField(max_length=500, blank=True, default='')
    log_path = models.CharField(max_length=500, blank=True, default='')
    retry_of = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='retries',
    )
    cancel_requested_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='cancelled_crawl_runs',
    )
    cancel_requested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-queued_at']
        verbose_name = '抓取任务'
        verbose_name_plural = '抓取任务'
        constraints = [
            models.UniqueConstraint(
                fields=['target'],
                condition=models.Q(status__in=['queued', 'running', 'cancel_requested']),
                name='one_active_crawl_run_per_target',
            ),
        ]


class SearchIndexSettings(models.Model):
    """Singleton configuration and liveness state for semantic indexing."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=True)
    interval_seconds = models.PositiveIntegerField(default=300)
    batch_size = models.PositiveIntegerField(default=100)
    active_collection = models.CharField(max_length=128, default='news_embeddings')
    model_name = models.CharField(
        max_length=255,
        default='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    )
    schema_version = models.CharField(max_length=64, default='news-v1')
    next_run_at = models.DateTimeField(null=True, blank=True)
    worker_heartbeat_at = models.DateTimeField(null=True, blank=True)
    worker_instance_id = models.CharField(max_length=128, blank=True, default='')
    last_success_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='search_index_settings_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '语义索引设置'
        verbose_name_plural = '语义索引设置'


class SearchIndexRun(models.Model):
    TRIGGER_CHOICES = [
        ('startup', 'Startup'),
        ('scheduled', 'Scheduled'),
        ('crawl_batch', 'Crawl batch'),
        ('manual', 'Manual'),
        ('recovery', 'Recovery'),
    ]
    MODE_CHOICES = [('sync', 'Sync'), ('rebuild', 'Rebuild')]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('cancel_requested', 'Cancel requested'),
        ('cancelled', 'Cancelled'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default='sync')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='queued', db_index=True)
    active_slot = models.PositiveSmallIntegerField(default=1, editable=False)
    worker_instance_id = models.CharField(max_length=128, blank=True, default='')
    crawl_batch = models.ForeignKey(
        CrawlBatch, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='search_index_runs',
    )
    requested_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='requested_search_index_runs',
    )
    collection_name = models.CharField(max_length=128, blank=True, default='')
    model_name = models.CharField(max_length=255, blank=True, default='')
    schema_version = models.CharField(max_length=64, blank=True, default='')
    news_count = models.PositiveIntegerField(default=0)
    vector_count_before = models.PositiveIntegerField(default=0)
    vector_count_after = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    orphaned_count = models.PositiveIntegerField(default=0)
    upserted_count = models.PositiveIntegerField(default=0)
    deleted_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    safe_error_code = models.CharField(max_length=64, blank=True, default='')
    safe_error_message = models.CharField(max_length=500, blank=True, default='')
    queued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='cancelled_search_index_runs',
    )
    cancel_requested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-queued_at']
        verbose_name = '语义索引任务'
        verbose_name_plural = '语义索引任务'
        constraints = [
            models.UniqueConstraint(
                fields=['active_slot'],
                condition=models.Q(status__in=['queued', 'running', 'cancel_requested']),
                name='one_active_search_index_run',
            ),
            models.UniqueConstraint(
                fields=['crawl_batch'],
                condition=models.Q(crawl_batch__isnull=False),
                name='one_search_index_run_per_crawl_batch',
            ),
        ]
