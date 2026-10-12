from django.db import migrations, models
import django.db.models.deletion


INITIAL_JINA_DOMAINS = (
    'bbc.co.uk',
    'bbc.com',
    'developer.chrome.com',
    'technologyreview.com',
    'venturebeat.com',
)


def seed_jina_policies(apps, schema_editor):
    policy = apps.get_model('api', 'JinaFallbackPolicy')
    policy.objects.bulk_create([
        policy(domain=domain, enabled=True, auto_discovered=False)
        for domain in INITIAL_JINA_DOMAINS
    ])


def remove_seeded_jina_policies(apps, schema_editor):
    policy = apps.get_model('api', 'JinaFallbackPolicy')
    policy.objects.filter(domain__in=INITIAL_JINA_DOMAINS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0034_add_litellm_provider_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='JinaFallbackPolicy',
            fields=[
                ('domain', models.CharField(max_length=253, primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(db_index=True, default=False)),
                ('auto_discovered', models.BooleanField(default=True)),
                ('failure_count', models.PositiveBigIntegerField(default=0)),
                ('last_failure_codes', models.JSONField(blank=True, default=list)),
                ('last_seen_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='jina_fallback_policy_updates',
                    to='auth.user',
                )),
            ],
            options={
                'verbose_name': 'Jina 回退域名策略',
                'verbose_name_plural': 'Jina 回退域名策略',
                'ordering': ['-last_seen_at', 'domain'],
            },
        ),
        migrations.CreateModel(
            name='ArticleFetchEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('domain', models.CharField(db_index=True, max_length=253)),
                ('outcome', models.CharField(choices=[('success', 'Success'), ('failed', 'Failed')], db_index=True, max_length=16)),
                ('provider', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('failure_codes', models.JSONField(blank=True, default=list)),
                ('quality_score', models.FloatField(blank=True, null=True)),
                ('content_length', models.PositiveIntegerField(default=0)),
                ('elapsed_ms', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('news', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='full_content_fetch_events',
                    to='api.news',
                )),
            ],
            options={
                'verbose_name': '全文抓取事件',
                'verbose_name_plural': '全文抓取事件',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='articlefetchevent',
            index=models.Index(fields=['domain', '-created_at'], name='idx_fetch_event_domain_time'),
        ),
        migrations.AddIndex(
            model_name='articlefetchevent',
            index=models.Index(fields=['outcome', '-created_at'], name='idx_fetch_event_outcome_time'),
        ),
        migrations.RunPython(seed_jina_policies, remove_seeded_jina_policies),
    ]
