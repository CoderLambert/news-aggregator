"""In-memory enumeration/commit receipts, never a raw feed cache."""
from dataclasses import dataclass, field
import uuid

from api.services.feed_state import commit_feed_checkpoint, defer_feed


@dataclass
class FeedReceipt:
    context: object
    expected_entries: int
    etag: str
    last_modified: str
    effective_url: str
    receipt_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    enumerated: bool = False
    terminal: dict = field(default_factory=dict)

    def token(self, index):
        return f'{self.receipt_id}:{index}'

    def settle(self, index, outcome, reason='', *, changed=False, body_committed=False):
        if outcome not in {'committed', 'policy_skip', 'deferred', 'failed'} or not 0 <= index < self.expected_entries:
            raise ValueError('invalid_receipt_result')
        if index in self.terminal:
            return False
        self.terminal[index] = (outcome, reason, changed, body_committed)
        return True

    @property
    def complete(self):
        return self.enumerated and len(self.terminal) == self.expected_entries

    @property
    def can_checkpoint(self):
        return self.complete and all(value[0] in {'committed', 'policy_skip'} for value in self.terminal.values())


class FeedReceiptRegistry:
    def __init__(self):
        self.receipts = {}
        self.active_pipeline_tasks = set()

    def add(self, receipt):
        self.receipts[receipt.receipt_id] = receipt
        return receipt

    def settle(self, token, outcome, reason='', **kwargs):
        if not token:
            return False
        identity, index = token.rsplit(':', 1)
        return self.receipts[identity].settle(int(index), outcome, reason, **kwargs)

    def finish(self, reason):
        """Called after the engine has drained Pipeline tasks; CAS may still lose."""
        totals = dict(entries_seen=0, entries_committed=0, entries_changed=0,
                      body_candidates_committed=0, policy_skips_by_reason={}, parse_failures=0,
                      persistence_failures=0, checkpoint_committed=False)
        outcomes = []
        checkpoints = 0
        for receipt in self.receipts.values():
            totals['entries_seen'] += receipt.expected_entries
            for outcome, code, changed, body in receipt.terminal.values():
                if outcome == 'committed':
                    totals['entries_committed'] += 1
                    totals['entries_changed'] += int(changed)
                    totals['body_candidates_committed'] += int(body)
                elif outcome == 'policy_skip':
                    skips = totals['policy_skips_by_reason']
                    skips[code] = skips.get(code, 0) + 1
                else:
                    totals['persistence_failures'] += 1
            totals['persistence_failures'] += receipt.expected_entries - len(receipt.terminal)
            if reason == 'finished' and receipt.can_checkpoint:
                committed = commit_feed_checkpoint(receipt.context, etag=receipt.etag,
                                                    last_modified=receipt.last_modified, effective_url=receipt.effective_url)
                if committed:
                    checkpoints += 1
                    outcomes.append('valid_empty' if receipt.expected_entries == 0 else
                                    'updated' if any(v[2] for v in receipt.terminal.values()) else 'unchanged')
                else:
                    outcomes.append('deferred')
            else:
                defer_feed(receipt.context)
                outcomes.append('partial')
        totals['checkpoint_committed'] = bool(self.receipts) and checkpoints == len(self.receipts)
        totals['outcome'] = ('partial' if 'partial' in outcomes else 'deferred' if 'deferred' in outcomes else
                             'updated' if 'updated' in outcomes else 'unchanged' if 'unchanged' in outcomes else
                             'valid_empty' if outcomes else 'deferred')
        return totals
