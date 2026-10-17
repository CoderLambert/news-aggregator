"""Low-confidence topic hints stay bounded and never infer from one headline."""
from api.services.channel_topic_hints import infer_title_topics


def test_matching_titles_give_only_reviewable_topic_evidence():
    hints = infer_title_topics([
        'React server components improve client boundaries',
        'TypeScript tools for application interfaces',
        'CSS grid layout and browser rendering update',
        'Weekend editorial news roundup',
    ])
    assert hints == [{'topic_key': 'frontend', 'matched_titles': 3, 'total_titles': 4}]


def test_duplicate_titles_and_repeated_keywords_do_not_raise_confidence():
    assert infer_title_topics([
        'React React React server components',
        ' react   react react SERVER components ',
        'Ordinary editorial update',
    ]) == []


def test_sparse_and_mixed_topics_return_no_confident_suggestion():
    assert infer_title_topics([
        'One React release',
        'A clinical trial update',
        'A solar power plant announcement',
        'Quarterly earnings and venture capital',
    ]) == []
    assert infer_title_topics(['React components', 'TypeScript release']) == []
