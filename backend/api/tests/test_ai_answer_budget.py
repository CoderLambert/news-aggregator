"""Prompt and language-budget helpers. No provider calls."""
from django.test import SimpleTestCase

from api.services.ai_article_chat import (
    SUMMARY_CHAT_OUTPUT_TOKENS, chat_output_token_budget, summary_answer_requested,
)
from api.services.ai_private_translation import mostly_chinese_source


class AnswerBudgetTests(SimpleTestCase):
    def test_summary_intents_are_short_and_detail_requests_stay_open(self):
        self.assertTrue(summary_answer_requested('这篇文章的核心信息是什么？'))
        self.assertTrue(summary_answer_requested('帮我用一句话总结这篇文章'))
        self.assertTrue(summary_answer_requested('tl;dr'))
        self.assertFalse(summary_answer_requested('What happened?'))
        self.assertFalse(summary_answer_requested('请详细分析这篇文章为什么重要'))
        self.assertFalse(summary_answer_requested('请详细说明核心信息'))
        self.assertEqual(chat_output_token_budget('核心观点', ceiling=2048), SUMMARY_CHAT_OUTPUT_TOKENS)
        self.assertEqual(chat_output_token_budget('请逐段分析', ceiling=16000), 16000)
        self.assertEqual(chat_output_token_budget('摘要', ceiling=128), 128)

    def test_mostly_chinese_ignores_code_and_a_single_name(self):
        chinese = '这是一篇中文新闻稿，无需再次翻译。' * 2
        named = 'Alibaba 阿里巴巴 reported record cloud revenue this quarter. ' * 20
        japanese = 'これは日本語のニュース記事です。東京で会議が開かれました。' * 4
        fenced = chinese + '\n\n```py\nprint("lots of english identifiers in a fence")\n```\n'
        self.assertTrue(mostly_chinese_source(chinese))
        self.assertTrue(mostly_chinese_source(fenced))
        self.assertFalse(mostly_chinese_source(named))
        self.assertFalse(mostly_chinese_source(japanese))
        self.assertFalse(mostly_chinese_source(''))
        self.assertFalse(mostly_chinese_source('中国'))
