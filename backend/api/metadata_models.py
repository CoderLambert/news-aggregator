"""Append-only evidence for explicit, reviewable metadata correction batches."""
import uuid
from django.db import models


class MetadataCorrectionAudit(models.Model):
    run_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    entity = models.CharField(max_length=24)
    object_pk = models.PositiveBigIntegerField()
    source_key = models.CharField(max_length=80)
    input_hash = models.CharField(max_length=64)
    before = models.JSONField()
    after = models.JSONField()
    operator = models.CharField(max_length=80)
    applied_at = models.DateTimeField(auto_now_add=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run_id', 'entity', 'object_pk'], name='unique_metadata_correction')]
