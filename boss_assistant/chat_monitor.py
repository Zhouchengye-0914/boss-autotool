from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .actions import find_unique, human_click
from .config import ChatConfig, ResumeConfig
from .deepseek import DeepSeekError, DeepSeekResumeMatcher, choose_resume
from .persistence import SHANGHAI
from .records import MessageRecord
from .monitor import LayeredReporter
from .resume_sender import ChatResumeSender
from . import selectors

CHAT_URL = "https://www.zhipin.com/web/geek/chat"


@dataclass(frozen=True)
class InvitationDecision:
    classification: str
    keyword: str = ""


class ResumeInvitationClassifier:
    """只把具有明确动作语义的消息判为简历邀请。"""

    EXPLICIT_PATTERNS = (
        r"发(?:一份|下|一下|份)?(?:附件)?简历",
        r"发送(?:一份|下|一下|份)?(?:附件)?简历",
        r"提供(?:一份|下|一下|份)?简历",
        r"投递(?:一份|下|一下|份)?简历",
        r"上传(?:一份|下|一下|份)?简历",
        r"简历(?:方便|可以|能否|麻烦).{0,8}(?:发|发送|提供|投递)",
        r"请求.{0,8}发送简历",
    )
    MANUAL_PATTERNS = (r"简历", r"附件", r"资料")

    def classify(self, text: str) -> InvitationDecision:
        compact = re.sub(r"\s+", "", text or "")
        for pattern in self.EXPLICIT_PATTERNS:
            match = re.search(pattern, compact, re.IGNORECASE)
            if match:
                return InvitationDecision("explicit", match.group(0))
        for pattern in self.MANUAL_PATTERNS:
            if re.search(pattern, compact, re.IGNORECASE):
                return InvitationDecision("manual_review", pattern)
        return InvitationDecision("none")


REJECTION_PATTERN = re.compile(r"不合适|不匹配|很遗憾|暂不考虑|已招到|不太符合|停止招聘")
INTERVIEW_PATTERN = re.compile(r"面试|面谈|视频面|电话面|到公司|来公司|面邀|邀约|方便.{0,8}(?:时间|几点)")


@dataclass
class ChatCheckResult:
    unread_conversations: int = 0
    new_messages: int = 0
    explicit_invitations: int = 0
    manual_reviews: int = 0
    refreshed: bool = False
    skipped_not_due: bool = False


class ChatMonitor:
    """固定聊天标签页的同步轮询器，不创建线程、不自动发送附件。"""

    def __init__(
        self,
        tab: Any,
        config: ChatConfig,
        store: Any,
        reporter: LayeredReporter,
        resume_config: ResumeConfig | None = None,
        chat_db: Any | None = None,
        profile_text: str = "",
        *,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.tab = tab
        self.config = config
        self.store = store
        self.reporter = reporter
        self.rng = rng or random.Random()
        self.clock = clock
        self.sleeper = sleeper
        self.classifier = ResumeInvitationClassifier()
        self.resume_config = resume_config
        self.chat_db = chat_db
        self.profile_text = profile_text
        self.resume_matcher = DeepSeekResumeMatcher(resume_config.deepseek) if resume_config else None
        self.resume_sender = ChatResumeSender(tab, rng=self.rng, sleeper=self.sleeper)
        self.last_refresh_at = 0.0
        self.next_poll_at = self.clock() + self._next_interval()

    def _next_interval(self) -> float:
        return self.rng.uniform(self.config.min_poll_seconds, self.config.max_poll_seconds)

    def _activate(self) -> None:
        try:
            self.tab.set.activate()
        except Exception:
            pass

    def _ensure_chat_page(self, allow_refresh: bool) -> bool:
        self._activate()
        now = self.clock()
        url = str(getattr(self.tab, "url", "") or "")
        if "/web/geek/chat" not in url:
            self.tab.get(CHAT_URL)
            self.sleeper(self.rng.uniform(1, 3))
            self.last_refresh_at = now
            return True
        stale = now - self.last_refresh_at >= self.config.refresh_if_stale_seconds
        if allow_refresh and stale:
            try:
                self.tab.refresh()
                self.sleeper(self.rng.uniform(1, 3))
                self.last_refresh_at = now
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def _positive_rect(element: Any) -> bool:
        try:
            size = element.rect.size
            width, height = (
                (size.get("width", 0), size.get("height", 0))
                if isinstance(size, dict) else (size[0], size[1])
            )
            return float(width) > 0 and float(height) > 0
        except Exception:
            return False

    def _unread_items(self) -> list[Any]:
        items: list[Any] = []
        seen: set[str] = set()
        for locator in selectors.CHAT_UNREAD_BADGES:
            try:
                badges = self.tab.eles(locator, timeout=0.5)
            except Exception:
                continue
            for badge in badges:
                if not self._positive_rect(badge):
                    continue
                item = badge
                fallback = None
                for _ in range(7):
                    try:
                        parent = item.parent()
                    except Exception:
                        break
                    if parent is None:
                        break
                    item = parent
                    klass = str(item.attr("class") or "").lower()
                    if "friend-content-warp" in klass:
                        break
                    if any(word in klass for word in ("conversation-item", "chat-list-item")):
                        break
                    if "friend-content" in klass:
                        fallback = item
                else:
                    item = fallback or item
                if not self._positive_rect(item):
                    continue
                identity = str(item.attr("data-id") or item.attr("data-v-uid") or item.text or "")
                if identity and identity not in seen:
                    seen.add(identity)
                    items.append(item)
        return items[: self.config.max_conversations_per_cycle]

    @staticmethod
    def _conversation_meta(item: Any) -> tuple[str, str]:
        text = (getattr(item, "text", "") or "").strip()
        contact_name = ""
        for locator in selectors.CHAT_CONTACT_NAME:
            try:
                name_element = item.ele(locator, timeout=0.2)
                contact_name = (name_element.text or "").strip() if name_element else ""
            except Exception:
                continue
            if contact_name:
                break
        contact_name = contact_name.splitlines()[0].strip() if contact_name else (
            text.splitlines()[0].strip() if text else "未知联系人"
        )
        conversation_id = str(
            item.attr("data-id") or item.attr("data-v-uid") or item.attr("data-user-id") or ""
        ).strip()
        if not conversation_id:
            # 列表时间和最后一条消息会持续变化，不能参与幂等键。
            stable_contact = re.sub(r"\s+", " ", contact_name)[:160]
            conversation_id = f"contact:{stable_contact}"
        return conversation_id, contact_name

    def _job_meta(self) -> tuple[str, str]:
        try:
            title = self.tab.ele("css:.chat-position-content .position-name", timeout=0.5)
            title_text = (title.text or "").strip() if title else ""
            if title_text:
                return title_text, ""
        except Exception:
            pass
        for locator in selectors.CHAT_JOB_INFO:
            try:
                element = self.tab.ele(locator, timeout=0.5)
                text = (element.text or "").strip() if element else ""
                if text:
                    parts = [part.strip() for part in text.splitlines() if part.strip()]
                    company = parts[1] if len(parts) > 1 and parts[1] != "查看职位" else ""
                    return (parts[0] if parts else "", company)
            except Exception:
                continue
        return "", ""

    def _visible_messages(self, conversation_id: str, contact_name: str) -> list[MessageRecord]:
        elements: list[Any] = []
        for locator in selectors.CHAT_MESSAGE_ITEMS:
            try:
                candidates = [e for e in self.tab.eles(locator, timeout=0.5) if self._positive_rect(e)]
            except Exception:
                continue
            if candidates:
                elements = candidates
                break
        job_title, company = self._job_meta()
        records: list[MessageRecord] = []
        for element in elements:
            text = (getattr(element, "text", "") or "").strip()
            if not text:
                continue
            classes = [str(element.attr("class") or "").lower()]
            parent = element
            for _ in range(3):
                try:
                    parent = parent.parent()
                    classes.append(str(parent.attr("class") or "").lower())
                except Exception:
                    break
            klass = " ".join(classes)
            direction = "outbound" if any(x in klass for x in ("myself", "self", "mine", "right")) else "inbound"
            records.append(
                MessageRecord(conversation_id, contact_name, "", job_title, company,
                              direction, text, datetime.now(SHANGHAI))
            )
        return records

    def _safe_send_reply(
        self, conversation_id: str, contact_name: str, based_on: str, reply: str
    ) -> tuple[bool, str]:
        """发送前刷新并比较消息指纹，防止与手机端或新到消息冲突。"""
        try:
            self.tab.refresh()
            self.sleeper(self.rng.uniform(1.5, 3.0))
            target = None
            for locator in selectors.CHAT_CONVERSATION_ITEMS:
                items = [x for x in self.tab.eles(locator, timeout=1) if self._positive_rect(x)]
                target = next((x for x in items if contact_name in (x.text or "")), None)
                if target: break
            if target is None:
                return False, "刷新后未找到原会话，取消自动回复"
            human_click(self.tab, target, rng=self.rng, sleeper=self.sleeper)
            self.sleeper(self.rng.uniform(0.5, 1.0))
            fresh = self._visible_messages(conversation_id, contact_name)
            if self.chat_db is not None:
                for message in fresh: self.chat_db.record_message(message)
            if not fresh or fresh[-1].fingerprint != based_on:
                return False, "消息已由手机端或对方更新，草稿作废"
            if fresh[-1].direction != "inbound":
                return False, "最后一条已经是己方消息，取消自动回复"
            field = find_unique(self.tab, selectors.GREETING_INPUT, timeout=1)
            if field is None:
                return False, "未找到唯一聊天输入框"
            try: field.clear()
            except Exception: pass
            field.input(reply)
            field.input("\n")
            self.sleeper(self.rng.uniform(1.0, 2.0))
            confirmed = self._visible_messages(conversation_id, contact_name)
            if any(message.direction == "outbound" and self._compact(reply) in self._compact(message.text)
                   for message in confirmed[-4:]):
                if self.chat_db is not None:
                    for message in confirmed: self.chat_db.record_message(message)
                return True, "自动回复已进入己方消息记录"
            return False, "自动回复结果未在消息气泡中确认"
        except Exception as exc:
            return False, f"自动回复异常: {type(exc).__name__}: {exc}"

    @staticmethod
    def _compact(text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    def verify_greeting_sent(self, task: Any) -> tuple[bool, str]:
        """刷新固定聊天页，并确认本次招呼语已进入己方消息气泡。"""
        self._activate()
        try:
            self.tab.refresh()
            self.sleeper(self.rng.uniform(1.5, 3.0))
            self.last_refresh_at = self.clock()
        except Exception as exc:
            return False, f"固定聊天页刷新失败: {exc}"
        items: list[Any] = []
        for locator in selectors.CHAT_CONVERSATION_ITEMS:
            try:
                items = [item for item in self.tab.eles(locator, timeout=1) if self._positive_rect(item)]
            except Exception:
                continue
            if items:
                break
        company = str(getattr(task, "company", "") or "").strip()
        title = str(getattr(task, "job_title", "") or "").strip()
        candidates = [item for item in items if company and company in (item.text or "")]
        if not candidates:
            # 刚建立/更新的会话通常位于列表首部；最多核对前五个，避免遍历整页。
            candidates = items[:5]
        expected = self._compact(str(getattr(task, "greeting", "") or ""))
        for item in candidates[:5]:
            try:
                human_click(self.tab, item, rng=self.rng, sleeper=self.sleeper)
                self.sleeper(self.rng.uniform(0.5, 1.0))
            except Exception:
                continue
            current_title, _ = self._job_meta()
            if title and current_title and self._compact(title) not in self._compact(current_title):
                continue
            try:
                bubbles = self.tab.eles("css:.message-item.item-myself", timeout=1)
            except Exception:
                bubbles = []
            if any(expected and expected in self._compact(getattr(bubble, "text", "") or "")
                   for bubble in bubbles):
                return True, "固定聊天页已确认招呼语进入己方消息记录"
            input_empty = False
            for locator in selectors.GREETING_INPUT:
                try:
                    field = self.tab.ele(locator, timeout=0.2)
                    if field and self._positive_rect(field):
                        value = str(field.attr("value") or getattr(field, "text", "") or "").strip()
                        input_empty = not value
                        break
                except Exception:
                    continue
            if input_empty:
                return False, "固定聊天页存在空输入框，但未找到本次己方消息，判定未发送"
        return False, "固定聊天页未找到与岗位匹配的已发送招呼语"

    def check(
        self, *, force: bool = False, allow_refresh: bool = True,
        allow_resume_send: bool = True, target_contact: str = "",
        max_conversations: int | None = None,
    ) -> ChatCheckResult:
        now = self.clock()
        if not force and now < self.next_poll_at:
            return ChatCheckResult(skipped_not_due=True)
        result = ChatCheckResult()
        try:
            result.refreshed = self._ensure_chat_page(allow_refresh)
            unread_items = self._unread_items()
            result.unread_conversations = len(unread_items)
            if target_contact:
                unread_items = [
                    item for item in unread_items
                    if target_contact in self._conversation_meta(item)[1]
                ]
            if max_conversations is not None:
                unread_items = unread_items[:max(0, max_conversations)]
            for item in unread_items:
                conversation_id, contact_name = self._conversation_meta(item)
                human_click(self.tab, item, rng=self.rng, sleeper=self.sleeper)
                self.sleeper(self.rng.uniform(0.5, 1.5))
                visible_messages = self._visible_messages(conversation_id, contact_name)
                if self.chat_db is not None and self.chat_db is not self.store:
                    for message in visible_messages:
                        self.chat_db.record_message(message)
                explicit_request = False
                latest_new_inbound = None
                for message in visible_messages:
                    if not self.store.add_message(message):
                        continue
                    result.new_messages += 1
                    if message.direction != "inbound":
                        continue
                    latest_new_inbound = message
                    decision = self.classifier.classify(message.text)
                    if decision.classification == "explicit":
                        explicit_request = True
                        if self.store.add_invitation(message, "explicit", decision.keyword):
                            result.explicit_invitations += 1
                    elif decision.classification == "manual_review":
                        if self.store.add_invitation(message, "manual_review", decision.keyword):
                            result.manual_reviews += 1
                ai_resume_request = False
                resume_key_override = ""
                if latest_new_inbound is not None and self.chat_db is not None:
                    text = latest_new_inbound.text
                    based_on = latest_new_inbound.fingerprint
                    if REJECTION_PATTERN.search(text):
                        self.chat_db.record_decision(conversation_id, based_on, "ignore", "",
                                                     "completed", "识别为拒绝或结束沟通")
                    elif INTERVIEW_PATTERN.search(text):
                        if self.chat_db.record_interview_alert(conversation_id, based_on, text):
                            self.reporter.attention(
                                f"检测到 {contact_name} 的面试相关消息，请在手机端人工接管；本会话已暂停自动回复。"
                            )
                    elif self.resume_matcher and self.resume_config and self.resume_config.deepseek.enabled:
                        job_title, company = self._job_meta()
                        profile_text = self.profile_text or "候选人具备数据分析、Python、SQL、AI应用项目及应届生经历"
                        conversation_text = "\n".join(
                            f"{m.direction}:{m.text}" for m in visible_messages[-8:]
                        )
                        try:
                            decision = self.resume_matcher.conversation_decision(
                                profile_text, f"{job_title}\n{company}", conversation_text,
                                self.resume_config.conversation_preferences,
                            )
                            action = decision["action"]
                            if action == "interview_alert":
                                self.chat_db.record_interview_alert(conversation_id, based_on, text)
                                self.reporter.attention(
                                    f"DeepSeek 判断 {contact_name} 涉及面试，请在手机端人工接管。"
                                )
                            elif action == "send_resume":
                                ai_resume_request = True
                                resume_key_override = decision["resume_key"]
                                self.chat_db.record_decision(conversation_id, based_on, action, "",
                                                             "approved", decision["reason"])
                            elif action == "reply" and decision["reply"]:
                                self.chat_db.record_decision(conversation_id, based_on, action,
                                                             decision["reply"], "drafted",
                                                             decision["reason"])
                                sent, reason = self._safe_send_reply(
                                    conversation_id, contact_name, based_on, decision["reply"]
                                )
                                self.chat_db.record_decision(
                                    conversation_id, based_on, action, decision["reply"],
                                    "sent" if sent else "cancelled", reason,
                                )
                                self.reporter.chat(f"{contact_name}：{reason}")
                            else:
                                self.chat_db.record_decision(conversation_id, based_on, "ignore", "",
                                                             "completed", decision["reason"])
                        except DeepSeekError as exc:
                            self.reporter.attention(f"{contact_name} 的 AI 判断失败，保持不回复：{exc}")
                proactive_contact = (
                    any(message.direction == "inbound" for message in visible_messages)
                    and not any(message.direction == "outbound" for message in visible_messages)
                )
                resume_cfg = self.resume_config
                should_send = bool(
                    allow_resume_send and resume_cfg and not self.store.resume_sent(conversation_id)
                    and (
                        (proactive_contact and resume_cfg.auto_send_on_proactive_contact)
                        or ((explicit_request or ai_resume_request)
                            and resume_cfg.auto_send_on_explicit_invitation)
                    )
                )
                if should_send and resume_cfg and self.resume_matcher:
                    job_title, company = self._job_meta()
                    job_text = "\n".join((job_title, company, *(m.text for m in visible_messages[-6:])))
                    try:
                        option = next(
                            (item for item in resume_cfg.options if item.key == resume_key_override),
                            None,
                        ) or choose_resume(job_text, resume_cfg.options, self.resume_matcher)
                        send_result = self.resume_sender.send(option)
                        self.store.record_resume_delivery(
                            conversation_id, job_title, company, option.key,
                            option.display_name, "success" if send_result.success else "failed",
                            send_result.reason,
                        )
                        if send_result.success:
                            self.reporter.chat(
                                f"已向 {contact_name} 发送 {option.key} 简历（岗位：{job_title or '未识别'}）。"
                            )
                        else:
                            self.reporter.attention(
                                f"{contact_name} 简历发送失败：{send_result.reason}；"
                                f"弹窗选项：{send_result.visible_options}"
                            )
                    except DeepSeekError as exc:
                        self.reporter.attention(str(exc))
            self.store.record_chat_check(
                result.unread_conversations, result.new_messages,
                result.explicit_invitations + result.manual_reviews,
            )
            self.reporter.chat(
                f"未读会话 {result.unread_conversations}，新增消息 {result.new_messages}，"
                f"明确简历邀请 {result.explicit_invitations}，待人工判断 {result.manual_reviews}"
            )
            if result.explicit_invitations:
                self.reporter.attention(
                    f"发现 {result.explicit_invitations} 条明确简历邀请，已入库等待附件匹配；本阶段未自动发送。"
                )
            return result
        except Exception as exc:
            self.store.record_chat_check(0, 0, 0, f"{type(exc).__name__}: {exc}")
            self.reporter.attention(f"聊天检查失败：{type(exc).__name__}: {exc}")
            return result
        finally:
            self.next_poll_at = self.clock() + self._next_interval()
