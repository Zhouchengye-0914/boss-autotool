import unittest

from boss_assistant.config import DeepSeekConfig, ResumeOptionConfig
from boss_assistant.deepseek import DeepSeekResumeMatcher, choose_resume


class ResumeMatcherTests(unittest.TestCase):
    def setUp(self):
        self.options = (
            ResumeOptionConfig("data", "数据版.pdf", 0, ("数据分析", "SQL")),
            ResumeOptionConfig("ops", "运营版.pdf", 1, ("数据运营", "策略运营")),
            ResumeOptionConfig("ai", "AI版.pdf", 2, ("AI", "大模型")),
        )
        self.matcher = DeepSeekResumeMatcher(
            DeepSeekConfig(False, "https://example.invalid", "model", "TEST_KEY", 1)
        )

    def test_local_keywords_choose_unique_resume(self):
        selected = choose_resume("AI产品经理，负责大模型应用", self.options, self.matcher)
        self.assertEqual(selected.key, "ai")

    def test_disabled_deepseek_has_no_network_dependency(self):
        selected = choose_resume("数据分析 SQL", self.options, self.matcher)
        self.assertEqual(selected.key, "data")

    def test_conversation_json_is_constrained(self):
        matcher = DeepSeekResumeMatcher(
            DeepSeekConfig(True, "https://example.com", "model", "TEST_KEY", 1)
        )
        matcher._chat = lambda *args, **kwargs: (
            '{"action":"reply","resume_key":"","reply":"您好，可以进一步了解岗位职责。",'
            '"reason":"HR提问"}'
        )
        decision = matcher.conversation_decision("profile", "job", "chat", "preferences")
        self.assertEqual(decision["action"], "reply")
        self.assertLessEqual(len(decision["reply"]), 80)


if __name__ == "__main__":
    unittest.main()
