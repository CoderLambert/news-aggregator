"""T03 owner-scoped, persisted per-purpose model selection.

A nullable task-specific selection explicitly inherits the user's default.
Soft-deleted models remain referenced for visible fail-closed reselection;
hard deletion is protected rather than silently reverting to a default.
"""
from django.conf import settings
from django.db import models

TASK_KINDS = (
    'default', 'article_qa', 'full_translation',
    'deep_research', 'question_suggestions',
)

SELECTION_SOURCES = (
    'unset', 'inherit', 'byok', 'chatgpt_subscription',
)




class UserAITaskPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='ai_task_preferences',
    )
    task_kind = models.CharField(
        max_length=32, choices=[(kind, kind) for kind in TASK_KINDS],
    )
    selection_source = models.CharField(
        max_length=32, choices=[(source, source) for source in SELECTION_SOURCES],
        default='inherit',
    )
    model_config = models.ForeignKey(
        'api.UserAIModelConfig', null=True, blank=True,
        on_delete=models.PROTECT, related_name='task_preferences',
    )
    # All five rows are written atomically with the same batch revision.
    # Zero denotes a never-written preference set.
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['task_kind']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'task_kind'], name='user_ai_task_preference_unique',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(selection_source='byok', model_config__isnull=False)
                    | models.Q(
                        selection_source__in=('unset', 'inherit', 'chatgpt_subscription'),
                        model_config__isnull=True,
                    )
                ),
                name='user_ai_task_preference_source_model',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(task_kind='default', selection_source__in=('unset', 'byok'))
                    | ~models.Q(task_kind='default')
                ),
                name='user_ai_task_preference_default_source',
            ),
        ]
