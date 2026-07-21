from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from .actions import find_unique, human_click
from .config import ResumeOptionConfig
from . import selectors


@dataclass(frozen=True)
class ResumeSendResult:
    success: bool
    reason: str
    visible_options: tuple[str, ...] = ()


class ChatResumeSender:
    """在已打开的单个聊天会话中按名称或索引发送附件简历。"""

    def __init__(self, tab: Any, *, rng: random.Random | None = None, sleeper=time.sleep):
        self.tab = tab
        self.rng = rng or random.Random()
        self.sleeper = sleeper

    @staticmethod
    def _visible(element: Any) -> bool:
        try:
            size = element.rect.size
            width, height = (size.get("width", 0), size.get("height", 0)) if isinstance(size, dict) else size
            return element.states.is_displayed and float(width) > 0 and float(height) > 0
        except Exception:
            return False

    def _resume_options(self) -> list[Any]:
        for locator in selectors.CHAT_RESUME_OPTIONS:
            try:
                options = [item for item in self.tab.eles(locator, timeout=1) if self._visible(item)]
            except Exception:
                continue
            if options:
                return options
        return []

    def send(self, option: ResumeOptionConfig) -> ResumeSendResult:
        button = find_unique(self.tab, selectors.CHAT_RESUME_BUTTON, timeout=1)
        if button is None:
            return ResumeSendResult(False, "未找到唯一可见的发简历按钮")
        human_click(self.tab, button, rng=self.rng, sleeper=self.sleeper)
        self.sleeper(self.rng.uniform(1, 2))
        options = self._resume_options()
        texts = tuple((getattr(item, "text", "") or "").strip() for item in options)
        selected = None
        if option.display_name:
            matches = [item for item in options if option.display_name in (getattr(item, "text", "") or "")]
            if len(matches) == 1:
                selected = matches[0]
        elif 0 <= option.option_index < len(options):
            selected = options[option.option_index]
        if selected is None:
            return ResumeSendResult(False, "三份简历中无法唯一匹配目标选项", texts)
        human_click(self.tab, selected, rng=self.rng, sleeper=self.sleeper)
        self.sleeper(self.rng.uniform(0.8, 1.5))
        confirm = find_unique(self.tab, selectors.CHAT_RESUME_CONFIRM, timeout=1)
        if confirm is None:
            return ResumeSendResult(False, "未找到唯一确认发送按钮", texts)
        human_click(self.tab, confirm, rng=self.rng, sleeper=self.sleeper)
        # BOSS 的弹窗关闭和系统消息写入存在异步延迟；最多等待 8 秒，避免
        # 因过早检查而把已送达误判为失败，进而在重试时重复投递。
        for _ in range(16):
            self.sleeper(0.5)
            if find_unique(self.tab, selectors.CHAT_RESUME_CONFIRM, timeout=0.2) is None:
                return ResumeSendResult(True, "附件简历已发送", texts)
            try:
                sent = self.tab.ele(
                    "xpath://*[contains(normalize-space(.), '已发送给Boss')]", timeout=0.2
                )
                if sent and self._visible(sent):
                    return ResumeSendResult(True, "附件简历已发送", texts)
            except Exception:
                pass
        return ResumeSendResult(False, "发送后 8 秒内结果仍未确认；重试前须先检查会话", texts)
