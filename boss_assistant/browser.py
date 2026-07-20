from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage

from .config import BrowserConfig

LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"


class BrowserStartError(RuntimeError):
    pass


@dataclass
class BrowserSession:
    page: ChromiumPage
    user_agent: str

    def quit(self) -> None:
        try:
            self.page.quit()
        except Exception:
            pass


def _persistent_user_agent(config: BrowserConfig, rng: random.Random) -> str:
    config.state_file.parent.mkdir(parents=True, exist_ok=True)
    if config.state_file.exists():
        try:
            state = json.loads(config.state_file.read_text(encoding="utf-8"))
            ua = state.get("user_agent")
            if isinstance(ua, str) and ua.strip():
                return ua
        except (OSError, json.JSONDecodeError):
            raise BrowserStartError(f"浏览器状态文件损坏: {config.state_file}")
    ua = rng.choice(config.user_agents)
    config.state_file.write_text(
        json.dumps({"user_agent": ua}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ua


def build_options(config: BrowserConfig, *, rng: random.Random | None = None) -> ChromiumOptions:
    if not config.executable_path.is_file():
        raise BrowserStartError(f"Chrome 不存在: {config.executable_path}")
    config.profile_path.mkdir(parents=True, exist_ok=True)
    ua = _persistent_user_agent(config, rng or random.Random())
    options = ChromiumOptions()
    options.set_browser_path(str(config.executable_path))
    options.set_user_data_path(str(config.profile_path))
    options.set_local_port(config.debug_port)
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument(f"--user-agent={ua}")
    options.set_argument("--disable-infobars")
    options.set_argument("--start-maximized")
    options.set_timeouts(page_load=config.page_load_timeout, base=config.element_timeout)
    return options


def create_browser(config: BrowserConfig) -> BrowserSession:
    options = build_options(config)
    try:
        page = ChromiumPage(options)
    except Exception as exc:
        raise BrowserStartError(
            "Chrome 启动或连接失败。请检查专用用户目录是否被占用、调试端口是否冲突，"
            f"以及 Chrome 路径是否正确。原始错误: {exc}"
        ) from exc
    ua = _persistent_user_agent(config, random.Random())
    return BrowserSession(page=page, user_agent=ua)


def open_login_page(session: BrowserSession) -> None:
    session.page.get(LOGIN_URL)
    print("请在 Chrome 中手动完成 BOSS 直聘登录。程序不会读取账号或密码。")
