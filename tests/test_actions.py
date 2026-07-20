import random
import unittest

from boss_assistant.actions import (
    find_first_with_text, find_unique, has_actionable_element, human_click,
)


class FakeScroll:
    def __init__(self, events): self.events = events
    def to_see(self): self.events.append("scroll")


class FakeRect:
    size = {"width": 100, "height": 40}


class FakeListRect:
    size = [100, 40]


class FakeElement:
    def __init__(self, events):
        self.scroll = FakeScroll(events)
        self.rect = FakeRect()
        self.states = type("States", (), {"is_displayed": True})()


class FakeActions:
    def __init__(self, events): self.events = events
    def move_to(self, element, **kwargs):
        self.events.append(("move", kwargs))
    def click(self, element=None): self.events.append("click")


class FakePage:
    def __init__(self, events): self.actions = FakeActions(events)


class HumanClickTests(unittest.TestCase):
    def test_scroll_move_click_order(self):
        events = []
        human_click(FakePage(events), FakeElement(events), rng=random.Random(1), sleeper=lambda _: None)
        self.assertEqual(events[0], "scroll")
        self.assertEqual(events[1][0], "move")
        self.assertEqual(events[2], "click")
        self.assertLessEqual(abs(events[1][1]["offset_x"]), 30)
        self.assertLessEqual(abs(events[1][1]["offset_y"]), 12)

    def test_unique_locator_rejects_ambiguous_elements(self):
        one = FakeElement([])

        class LocatorPage:
            def eles(self, locator):
                return [one, FakeElement([])] if locator == "many" else [one]

        page = LocatorPage()
        self.assertIs(find_unique(page, ("many", "one")), one)
        self.assertIsNone(find_unique(page, ("many",)))

    def test_click_accepts_real_drissionpage_list_size(self):
        events = []
        element = FakeElement(events)
        element.rect = FakeListRect()
        human_click(FakePage(events), element, rng=random.Random(2), sleeper=lambda _: None)
        self.assertEqual(events[-1], "click")

    def test_text_lookup_skips_empty_logo_link(self):
        empty = FakeElement([])
        empty.text = ""
        named = FakeElement([])
        named.text = "示例公司"

        class TextPage:
            def eles(self, locator):
                return [empty, named]

        self.assertIs(find_first_with_text(TextPage(), ("company",)), named)

    def test_hidden_login_template_without_rect_is_ignored(self):
        hidden = FakeElement([])

        class NoRect:
            @property
            def size(self):
                raise RuntimeError("no rect")

        hidden.rect = NoRect()

        class LoginPage:
            def eles(self, locator):
                return [hidden]

        self.assertFalse(has_actionable_element(LoginPage(), ("login",)))


if __name__ == "__main__":
    unittest.main()
