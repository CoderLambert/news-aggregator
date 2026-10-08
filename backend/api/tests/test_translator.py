from unittest.mock import patch

from api.services import translator


def test_title_and_summary_translation_path_uses_mocked_google_translator():
    translator._translation_cache.clear()
    try:
        with patch('deep_translator.GoogleTranslator') as google_translator:
            google_translator.return_value.translate.side_effect = ['标题译文', '摘要译文']

            title_result = translator.translate('A unique test title', src='en', tgt='zh-CN')
            summary_result = translator.translate('A unique test summary', src='en', tgt='zh-CN')

        assert title_result == ('标题译文', None, None)
        assert summary_result == ('摘要译文', None, None)
        assert google_translator.call_count == 2
        assert all(call.kwargs == {'source': 'en', 'target': 'zh-CN'} for call in google_translator.call_args_list)
    finally:
        translator._translation_cache.clear()
