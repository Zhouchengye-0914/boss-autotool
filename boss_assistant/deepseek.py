from __future__ import annotations

import json
import os
import urllib.request

from .config import DeepSeekConfig, ResumeOptionConfig


class DeepSeekError(RuntimeError):
    pass


def _secret_from_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value or os.name != "nt":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            stored, _ = winreg.QueryValueEx(key, name)
        return str(stored).strip()
    except (OSError, ImportError):
        return ""


class DeepSeekResumeMatcher:
    """OpenAI 兼容接口；默认关闭，密钥只从环境变量读取。"""

    def __init__(self, config: DeepSeekConfig):
        self.config = config

    def choose(self, job_text: str, options: tuple[ResumeOptionConfig, ...]) -> str:
        if not self.config.enabled:
            return ""
        api_key = _secret_from_environment(self.config.api_key_env)
        if not api_key:
            raise DeepSeekError(f"缺少环境变量 {self.config.api_key_env}")
        keys = [option.key for option in options]
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "只返回最匹配的简历 key，不要解释。候选：" + ",".join(keys)},
                {"role": "user", "content": job_text[:8000]},
            ],
        }
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise DeepSeekError(f"DeepSeek 匹配失败：{exc}") from exc
        return answer if answer in keys else ""

    def _chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        if not self.config.enabled:
            raise DeepSeekError("DeepSeek 未启用")
        api_key = _secret_from_environment(self.config.api_key_env)
        if not api_key:
            raise DeepSeekError(f"缺少环境变量 {self.config.api_key_env}")
        payload = {"model": self.config.model, "temperature": temperature,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user[:12000]}]}
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            return str(data["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise DeepSeekError(f"DeepSeek 请求失败：{exc}") from exc

    def greeting(self, profile_text: str, job_text: str) -> str:
        answer = self._chat(
            "你是求职沟通助手。根据候选人简历与JD写一条中文BOSS招呼语。"
            "必须真实，不虚构；突出最多两个最相关点；不超过70个汉字；只输出招呼语。",
            f"候选人：\n{profile_text[:6000]}\n\n岗位：\n{job_text[:5000]}",
        )
        return " ".join(answer.split())[:100]

    def conversation_decision(
        self, profile_text: str, job_text: str, conversation_text: str,
        preferences: str,
    ) -> dict[str, str]:
        answer = self._chat(
            "你是谨慎的求职聊天助手。只输出JSON对象，字段为action、resume_key、reply、reason。"
            "action只能是ignore、send_resume、reply、interview_alert。"
            "明确拒绝或结束沟通用ignore；涉及面试时间、地点、视频/电话面试或面试邀约弹窗必须用interview_alert，绝不代替用户确认；"
            "索要简历用send_resume；其余只有确实需要回答的问题才用reply。"
            "resume_key只能是general、ai、data或空。reply必须简短真实，不超过60个汉字，不编造经历、时间或意愿。",
            f"求职偏好：{preferences[:2000]}\n候选人：{profile_text[:5000]}\n"
            f"岗位：{job_text[:3000]}\n最近聊天：{conversation_text[:4000]}",
            temperature=0.1,
        )
        try:
            cleaned = answer.strip().removeprefix("```json").removesuffix("```").strip()
            value = json.loads(cleaned)
        except (json.JSONDecodeError, AttributeError) as exc:
            raise DeepSeekError(f"DeepSeek 决策不是有效 JSON：{exc}") from exc
        action = str(value.get("action") or "ignore")
        if action not in {"ignore", "send_resume", "reply", "interview_alert"}:
            action = "ignore"
        reply = " ".join(str(value.get("reply") or "").split())[:80]
        return {"action": action, "resume_key": str(value.get("resume_key") or ""),
                "reply": reply, "reason": str(value.get("reason") or "")[:200]}


def choose_resume(
    job_text: str, options: tuple[ResumeOptionConfig, ...], matcher: DeepSeekResumeMatcher
) -> ResumeOptionConfig:
    lowered = job_text.lower()
    scores = [sum(1 for keyword in option.keywords if keyword.lower() in lowered) for option in options]
    best = max(scores, default=0)
    if best > 0 and scores.count(best) == 1:
        return options[scores.index(best)]
    selected_key = matcher.choose(job_text, options)
    for option in options:
        if option.key == selected_key:
            return option
    return options[0]
