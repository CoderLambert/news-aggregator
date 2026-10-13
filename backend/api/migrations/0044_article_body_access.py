from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('api', '0043_smart_channel_workspace'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterModelOptions(name='news', options={'ordering': ['-publish_time'], 'verbose_name': '新闻', 'verbose_name_plural': '新闻', 'permissions': [('view_article_body', '可查看正文并按需请求获取')]}),
        migrations.AddField(model_name='news', name='full_content_requested_by', field=models.ForeignKey(blank=True, null=True, editable=False, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
    ]
