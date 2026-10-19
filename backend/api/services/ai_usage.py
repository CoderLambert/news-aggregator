"""Secret-free receipts at the one actual SDK send; never retry model IO for metrics."""
import logging
import time

from django.utils import timezone
from api.ai_model_models import AICallAttempt

logger = logging.getLogger(__name__)


def _get(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _tokens(value):
    return value if type(value) is int and 0 <= value <= 9_007_199_254_740_991 else None


class _Receipt:
    def __init__(self, selection, task_kind):
        self.started = time.monotonic()
        # This insert is before the send. If it fails no model request is made.
        self.row = AICallAttempt.objects.create(
            user_id=selection.user_id, task_kind=task_kind,
            model_config_id=selection.model_config_id, model_id=selection.model_id,
            provider_id=selection.connection.provider_id,
        )
        self.finished = False

    def finish(self, status, usage=None):
        if self.finished:
            return
        self.finished = True
        try:
            AICallAttempt.objects.filter(pk=self.row.pk, status='started').update(
                status=status, completed_at=timezone.now(),
                latency_ms=min(int((time.monotonic() - self.started) * 1000), 2_147_483_647),
                input_tokens=_tokens(_get(usage, 'prompt_tokens')) if status == 'succeeded' else None,
                output_tokens=_tokens(_get(usage, 'completion_tokens')) if status == 'succeeded' else None,
            )
        except Exception as exc:
            # Leave an unfinished receipt visibly unknown, never lose/retry a
            # successful provider result because writing statistics failed.
            logger.info('AI usage receipt unavailable (%s)', type(exc).__name__)


class _ObservedStream:
    def __init__(self, stream, receipt):
        self.stream, self.receipt = stream, receipt
        self.iterated = False

    def __iter__(self):
        if self.iterated:
            raise RuntimeError('AI response stream cannot be replayed')
        self.iterated = True
        stop, invalid, usage = False, False, None
        try:
            for frame in self.stream:
                frame_usage = _get(frame, 'usage')
                if frame_usage is not None:
                    usage = frame_usage
                for choice in _get(frame, 'choices') or []:
                    reason = _get(choice, 'finish_reason')
                    if reason == 'stop':
                        if stop:
                            invalid = True
                        stop = True
                    elif reason is not None:
                        invalid = True
                yield frame
            self.receipt.finish('succeeded' if stop and not invalid else 'unknown', usage)
        except BaseException:
            self.receipt.finish('unknown')
            raise

    def close(self):
        self.receipt.finish('unknown')
        self.stream.close()


def complete_with_usage(client, selection, task_kind, **kwargs):
    """One receipt per attempted upstream create, including every tool/chunk round."""
    if (selection.user_id != selection.connection.user_id
            or selection.task_kind != task_kind
            or task_kind not in {'article_qa', 'full_translation', 'deep_research', 'question_suggestions'}):
        raise ValueError('Invalid AI usage owner or task')
    if kwargs.get('stream') is True:
        kwargs.setdefault('stream_options', {'include_usage': True})
    receipt = _Receipt(selection, task_kind)
    try:
        result = client.chat.completions.create(**kwargs)
    except Exception as exc:
        status_code = getattr(exc, 'status_code', None)
        receipt.finish('failed' if type(status_code) is int else 'unknown')
        raise
    if kwargs.get('stream') is True:
        return _ObservedStream(result, receipt)
    choices = _get(result, 'choices') or []
    valid = len(choices) == 1 and _get(choices[0], 'finish_reason') in ('stop', 'tool_calls')
    receipt.finish('succeeded' if valid else 'unknown', _get(result, 'usage'))
    return result
