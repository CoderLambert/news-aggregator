from api.services.llm_translator import TRANSLATION_SYSTEM, build_translation_prompt


def test_translation_system_forbids_translating_code_and_python_name():
    assert 'Python 不能翻译为“蟒蛇”' in TRANSLATION_SYSTEM
    assert 'Markdown fenced code block' in TRANSLATION_SYSTEM
    assert '逐字符原样保留' in TRANSLATION_SYSTEM
    assert 'Markdown inline code' in TRANSLATION_SYSTEM


def test_build_translation_prompt_marks_code_as_untranslatable():
    prompt = build_translation_prompt('```python\nprint("hello")\n```')

    assert '不要翻译、改写或格式化任何 fenced code block' in prompt
    assert '不要翻译任何反引号包裹的 inline code' in prompt
    assert 'Python 绝不能翻译为“蟒蛇”' in prompt
    assert '<<<MARKDOWN_ARTICLE>>>' in prompt
    assert '```python\nprint("hello")\n```' in prompt
