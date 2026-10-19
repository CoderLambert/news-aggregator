import pytest
from api.services.ai_suggestions import parse_questions, SuggestionsError


def test_exactly_three_distinct_bounded_questions():
    assert parse_questions('[" A? ", "B?", "C?"]') == ['A?', 'B?', 'C?']
    for raw in ['[]', '["A?", "A?", "C?"]', '["A?", 2, "C?"]', '{"questions": []}', 'incomplete']:
        with pytest.raises(SuggestionsError):
            parse_questions(raw)
