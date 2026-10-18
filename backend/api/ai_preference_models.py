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


class UserAITaskPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='ai_task_preferences',
    )
    task_kind = models.CharField(
        max_length=32, choices=[(kind, kind) for kind in TASK_KINDS],
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
        ]
