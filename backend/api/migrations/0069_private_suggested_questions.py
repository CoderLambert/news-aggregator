from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('api', '0068_researchsession_native_continuation'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='PrivateSuggestedQuestions',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('source_hash', models.CharField(max_length=64)),
            ('execution_digest', models.CharField(max_length=64)),
            ('prompt_version', models.PositiveSmallIntegerField(default=1)),
            ('questions', models.JSONField(default=list)),
            ('model_source', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('news', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='api.news')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ],
        options={'constraints': [models.UniqueConstraint(
            fields=('user', 'news', 'source_hash', 'execution_digest', 'prompt_version'),
            name='private_suggestions_identity',
        )]},
    )]
