from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0057_rss_import_batches')]
    operations = [
        migrations.RemoveConstraint(model_name='chatgptarticletranslation', name='unique_chatgpt_news_translation'),
        migrations.AddConstraint(model_name='chatgptarticletranslation', constraint=models.UniqueConstraint(
            fields=['user', 'connection', 'news', 'source_hash'], name='unique_chatgpt_news_translation')),
    ]
