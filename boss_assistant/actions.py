from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Iterable

from .config import AppConfig
from .models import JobTask, OperationType, ResultStatus, TaskResult
from . import selectors


def _eles(page: Any, locator: str, timeout: float) -> list[Any]:
    try:
        return list(page.eles(locator, timeout=timeout))
    except TypeError:  # 测试替身或兼容旧接口
        return list(page.eles(locator))


def find_first(page: Any, locators: Iterable[str], timeout: float = 1) -> Any | None:
    for locator in locators:
        try:
            element = page.ele(locator, timeout=timeout)
            if element and getattr(element.states, "is_displayed", True):
                return element
        except Exception:
            continue
    return None


def find_first_with_text(page: Any, locators: Iterable[str], timeout: float = 1) -> Any | None:
    """返回首个可见且文本非空的元素。"""
    for locator in locators:
        try:
            for element in _eles(page, locator, timeout):
                if not getattr(element.states, "is_displayed", True):
                    continue
                if (getattr(element, "text", "") or "").strip():
                    return element
        except Exception:
            continue
    return None


def has_actionable_element(page: Any, locators: Iterable[str], timeout: float = 0.5) -> bool:
    """元素必须拥有正尺寸矩形，避免把隐藏登录/验证模板判为可见弹窗。"""
    for locator in locators:
        try:
            for element in _eles(page, locator, timeout):
                try:
                    size = element.rect.size
                    width, height = (
                        (size.get("width", 0), size.get("height", 0))
                        if isinstance(size, dict) else (size[0], size[1])
                    )
                    if float(width) > 0 and float(height) > 0:
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def find_unique(page: Any, locators: Iterable[str], timeout: float = 1) -> Any | None:
    """返回第一个仅匹配一个可见元素的定位结果，避免误点重复按钮。"""
    for locator in locators:
        try:
            elements = _eles(page, locator, timeout)
            visible = []
            for element in elements:
                if not getattr(element.states, "is_displayed", True):
                    continue
                try:
                    size = element.rect.size
                    width, height = (
                        (size.get("width", 0), size.get("height", 0))
                        if isinstance(size, dict) else (size[0], size[1])
                    )
                    if float(width) <= 0 or float(height) <= 0:
                        continue
                except Exception:
                    continue
                visible.append(element)
            if len(visible) == 1:
                return visible[0]
        except Exception:
            continue
    return None


def human_click(
    page: Any,
    element: Any,
    *,
    rng: random.Random | None = None,
    sleeper=time.sleep,
) -> None:
    rng = rng or random.Random()
    try:
        element.scroll.to_see()
    except Exception:
        pass
    size = getattr(getattr(element, "rect", None), "size", {}) or {}
    if isinstance(size, dict):
        width, height = size.get("width", 20), size.get("height", 20)
    else:
        width, height = size[0], size[1]
    width = max(float(width), 4.0)
    height = max(float(height), 4.0)
    offset_x = rng.uniform(-width * 0.3, width * 0.3)
    offset_y = rng.uniform(-height * 0.3, height * 0.3)
    page.actions.move_to(
        element, offset_x=offset_x, offset_y=offset_y, duration=rng.uniform(0.25, 0.8)
    )
    sleeper(rng.uniform(0.08, 0.35))
    page.actions.click(element)


class BossTaskExecutor:
    def __init__(
        self, page: Any, config: AppConfig, *, sleeper=time.sleep,
        tab_factory: Any | None = None,
    ):
        self.page = page
        self.config = config
        self.sleeper = sleeper
        self._chat_context: Any | None = None
        self._chat_input: Any | None = None
        self.last_job_snapshot: dict[str, str] = {}
        self.tab_factory = tab_factory

    def _contexts(self) -> list[Any]:
        contexts = [self.page]
        try:
            contexts.extend(self.page.get_frames(timeout=0.5))
        except Exception:
            pass
        return contexts

    def _find_unique_context(
        self, locators: Iterable[str], timeout: float = 1
    ) -> tuple[Any | None, Any | None]:
        preferred = [self._chat_context] if self._chat_context is not None else []
        contexts = preferred + [ctx for ctx in self._contexts() if ctx is not self._chat_context]
        for context in contexts:
            element = find_unique(context, locators, timeout=timeout)
            if element is not None:
                return context, element
        return None, None

    def _find_first_context(
        self, locators: Iterable[str], timeout: float = 1
    ) -> tuple[Any | None, Any | None]:
        preferred = [self._chat_context] if self._chat_context is not None else []
        contexts = preferred + [ctx for ctx in self._contexts() if ctx is not self._chat_context]
        for context in contexts:
            element = find_first(context, locators, timeout=timeout)
            if element is not None:
                return context, element
        return None, None

    def _text(self, locators: Iterable[str]) -> str:
        element = find_first_with_text(self.page, locators)
        return (getattr(element, "text", "") or "").strip() if element else ""

    def _screenshot(self, task: JobTask, stage: str) -> str:
        directory = self.config.output.screenshots_dir
        directory.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in task.task_id)
        filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_id}_{stage}.png"
        path = directory / filename
        try:
            self.page.get_screenshot(path=str(path))
            return str(path)
        except Exception:
            return ""

    def is_login_required(self) -> bool:
        url = str(getattr(self.page, "url", "") or "")
        return "/web/user" in url or has_actionable_element(self.page, selectors.LOGIN_MARKERS)

    def is_security_check(self) -> bool:
        return has_actionable_element(self.page, selectors.SECURITY_MARKERS)

    def _close_known_popup(self, task: JobTask, stage: str) -> str:
        close_button = find_first(self.page, selectors.KNOWN_POPUP_CLOSE, timeout=0.5)
        if close_button is None:
            return ""
        screenshot = self._screenshot(task, f"popup_{stage}")
        try:
            human_click(self.page, close_button, sleeper=self.sleeper)
            self.sleeper(0.5)
        except Exception:
            pass
        return screenshot

    def wait_for_login(self) -> None:
        while self.is_login_required() or self.is_security_check():
            print("检测到登录页或安全验证，任务已暂停，请在 Chrome 中手动处理。")
            self.sleeper(self.config.browser.login_check_interval)

    def _already_done(self, task: JobTask) -> bool:
        return find_first(self.page, selectors.SUCCESS_MARKERS, timeout=1) is not None

    def _handle_resume(self, task: JobTask) -> tuple[bool, str]:
        if find_first(self.page, selectors.RESUME_DIALOG, timeout=2) is None:
            return True, ""
        exact = find_unique(
            self.page,
            (f"xpath://*[normalize-space(.)='{task.resume_name}']",),
        )
        if exact is None:
            stem = Path(task.resume_name).stem
            exact = find_unique(
                self.page,
                (f"xpath://*[contains(normalize-space(.), '{stem}')]",),
            )
        if exact is None and "在线简历" in task.resume_name:
            exact = find_unique(self.page, selectors.ONLINE_RESUME)
        if exact is None:
            return False, f"简历弹窗中未找到指定简历: {task.resume_name}"
        human_click(self.page, exact, sleeper=self.sleeper)
        return True, ""

    def _fill_greeting(self, task: JobTask) -> tuple[bool, str]:
        # 参考 boss-tool：优先直接操作聊天输入区，不把同文案草稿误当模板。
        input_context, input_ele = self._find_unique_context(
            selectors.GREETING_INPUT, timeout=1
        )
        if input_ele is None:
            return False, "未找到招呼语模板或输入框"
        self._chat_context = input_context
        self._chat_input = input_ele
        try:
            input_ele.clear()
        except Exception:
            pass
        try:
            input_ele.input(task.greeting)
        except Exception as exc:
            return False, f"招呼语输入失败: {exc}"
        return True, ""

    def execute(self, task: JobTask, attempt: int = 1) -> TaskResult:
        original_page = self.page
        temporary_tab = None
        try:
            self._chat_context = None
            self._chat_input = None
            if self.tab_factory is not None:
                temporary_tab = self.tab_factory(task.job_url)
                self.page = temporary_tab
                self.sleeper(2)
            else:
                self.page.get(task.job_url)
            self.wait_for_login()
            self._close_known_popup(task, "after_load")
            if find_first(self.page, selectors.CLOSED_MARKERS, timeout=2):
                return TaskResult(ResultStatus.SKIPPED, reason="职位已关闭或不存在", retryable=False)
            job_name = self._text(selectors.JOB_TITLE)
            company = self._text(selectors.COMPANY)
            job_description = self._text(selectors.JOB_DESCRIPTION)
            self.last_job_snapshot = {
                "job_title": job_name,
                "company": company,
                "job_description": job_description,
            }
            # “继续沟通/已沟通”只表示会话已经建立，不能证明本任务的招呼语
            # 已经发送。仍需进入会话并核对消息，避免首次弹窗发送失败后被
            # 下一次重试误判为成功。
            button_locators = (
                selectors.COMMUNICATE_BUTTON
                if task.operation_type is OperationType.COMMUNICATION
                else selectors.APPLICATION_BUTTON
            )
            button = find_unique(self.page, button_locators)
            if button is None:
                shot = self._screenshot(task, "action_button_missing")
                return TaskResult(
                    ResultStatus.FAILED, job_name, company, "未找到沟通或投递按钮", attempt, shot
                )
            human_click(self.page, button, sleeper=self.sleeper)
            self.sleeper(3)
            if self.is_login_required() or self.is_security_check():
                self.wait_for_login()
            # 已建立会话时也必须走发送动作。聊天输入框会保留未发送草稿，
            # 仅按全文匹配会把草稿误认成历史消息。真正的历史消息幂等核验
            # 将使用消息气泡专属选择器；在此之前不以页面同文案直接成功。
            ok, reason = self._fill_greeting(task)
            if not ok:
                shot = self._screenshot(task, "greeting_failed")
                return TaskResult(ResultStatus.FAILED, job_name, company, reason, attempt, shot)
            ok, reason = self._handle_resume(task)
            if not ok:
                shot = self._screenshot(task, "resume_failed")
                return TaskResult(ResultStatus.FAILED, job_name, company, reason, attempt, shot)
            # boss-tool 的主路径是输入后回车发送；若页面只插入换行或未清空，
            # 再回退到明确的发送按钮。
            if self._chat_input is not None:
                try:
                    self._chat_input.input("\n")
                    self.sleeper(1.5)
                    current_text = (getattr(self._chat_input, "text", "") or "").strip()
                    if not current_text:
                        return TaskResult(ResultStatus.SUCCESS, job_name, company, "回车发送成功", attempt)
                except Exception:
                    pass
            send_context, send = self._find_unique_context(selectors.SEND_BUTTON, timeout=1)
            if send is None:
                shot = self._screenshot(task, "send_missing")
                return TaskResult(ResultStatus.FAILED, job_name, company, "未找到发送按钮", attempt, shot)
            human_click(send_context, send, sleeper=self.sleeper)
            self.sleeper(2)
            if self._already_done(task):
                return TaskResult(ResultStatus.SUCCESS, job_name, company, "发送成功", attempt)
            _, sent_text = self._find_first_context((f"text={task.greeting}",), timeout=3)
            _, current_input = self._find_first_context(selectors.GREETING_INPUT, timeout=0.5)
            input_text = (getattr(current_input, "text", "") or "").strip() if current_input else ""
            if sent_text is not None or (current_input is not None and not input_text):
                return TaskResult(ResultStatus.SUCCESS, job_name, company, "消息已发送", attempt)
            shot = self._screenshot(task, "result_unconfirmed")
            return TaskResult(
                ResultStatus.FAILED, job_name, company, "发送结果未确认", attempt, shot
            )
        except Exception as exc:
            shot = self._screenshot(task, "unexpected")
            return TaskResult(
                ResultStatus.FAILED,
                reason=f"页面操作异常: {type(exc).__name__}: {exc}",
                attempt=attempt,
                screenshot_path=shot,
            )
        finally:
            if temporary_tab is not None:
                try:
                    temporary_tab.close()
                except Exception:
                    pass
                self.page = original_page
