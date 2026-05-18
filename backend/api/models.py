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
    name = models.CharField('来源名称', max_length=100, unique=True)
    url = models.URLField('来源网址', max_length=255)
    logo = models.URLField('Logo', max_length=255, blank=True, default='')
    country = models.CharField('国家', max_length=50, default='CN')
    language = models.CharField('语言', max_length=50, default='zh')
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
    author = models.CharField('作者', max_length=100, blank=True, default='')
    publish_time = models.DateTimeField('发布时间', db_index=True)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, verbose_name='来源')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, verbose_name='分类')
    url = models.URLField('原文链接', max_length=500, unique=True, db_index=True)
    cover_image = models.URLField('封面图', max_length=500, blank=True, default='')
    created_at = models.DateTimeField('入库时间', auto_now_add=True)

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
