from __future__ import annotations

import json
import os
import urllib.request

from .config import DeepSeekConfig, ResumeOptionConfig


class DeepSeekError(RuntimeError):
    pass


class DeepSeekResumeMatcher:
    """OpenAI 兼容接口；默认关闭，密钥只从环境变量读取。"""

    def __init__(self, config: DeepSeekConfig):
        self.config = config

    def choose(self, job_text: str, options: tuple[ResumeOptionConfig, ...]) -> str:
        if not self.config.enabled:
            return ""
        api_key = os.environ.get(self.config.api_key_env, "").strip()
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
