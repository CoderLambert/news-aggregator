from django.db import models


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

    # Full article content (fetched via Jina Reader)
    full_content = models.TextField('完整原文(Markdown)', blank=True, default='')
    full_content_fetched_at = models.DateTimeField('原文获取时间', null=True, blank=True)
    full_content_zh = models.TextField('完整原文(中文)', blank=True, default='')
    full_content_zh_fetched_at = models.DateTimeField('中文翻译时间', null=True, blank=True)

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
