from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0032_research_queued_input'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProviderCredential',
            fields=[
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,
                    related_name='provider_credential',
                    serialize=False,
                    to='auth.user',
                )),
                ('provider', models.CharField(
                    choices=[('volcengine', 'Volcengine ARK'), ('dashscope', 'DashScope')],
                    max_length=16,
                )),
                ('encrypted_api_key', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '用户模型凭据',
                'verbose_name_plural': '用户模型凭据',
            },
        ),
    ]
