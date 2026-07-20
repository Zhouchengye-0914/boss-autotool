JOB_TITLE = (
    "css:.job-title", "css:.job-name .name", "css:h1", "xpath://h1"
)
COMPANY = (
    "css:.company-info a:not(:empty)",
    "xpath://div[contains(@class, 'company-info')]//a[normalize-space(.)!='']",
    "css:.company-info a", "css:.company-name", "css:[class*='company-name']"
)
JOB_DESCRIPTION = (
    "css:.job-sec-text",
    "css:.job-detail-section .text",
    "css:[class*='job-detail'] [class*='description']",
)
COMMUNICATE_BUTTON = (
    "css:.info-primary .btn-startchat", "css:.job-op .btn-startchat",
    "css:.btn-startchat", "css:.btn-chat", "css:.chat-btn",
    "xpath://button[contains(normalize-space(.), '立即沟通')]",
    "xpath://a[contains(normalize-space(.), '立即沟通')]",
)
APPLICATION_BUTTON = (
    "xpath://button[contains(normalize-space(.), '投递')]",
    "xpath://a[contains(normalize-space(.), '投递')]",
)
GREETING_INPUT = (
    "css:.dialog-wrap textarea", "css:.chat-input textarea",
    "css:[class*='chat'] [contenteditable='true']",
    "css:[class*='dialog'] [contenteditable='true']",
)
SEND_BUTTON = (
    "css:button.btn-send:not(.disabled)",
    "xpath://button[normalize-space(.)='发送']",
    "xpath://button[contains(normalize-space(.), '确认发送')]",
    "css:.btn-send",
)
SUCCESS_MARKERS = (
    "text:沟通成功", "text:投递成功",
    "xpath://button[contains(normalize-space(.), '已沟通')]",
    "xpath://button[contains(normalize-space(.), '继续沟通')]",
    "xpath://a[contains(normalize-space(.), '继续沟通')]",
)
LOGIN_MARKERS = (
    "css:.login-register", "css:.login-qrcode", "text:扫码登录", "text:立即登录"
)
SECURITY_MARKERS = ("text:验证码", "text:安全验证", "text:请完成验证")
RESUME_DIALOG = ("text:选择简历", "text:请选择简历", "css:.resume-dialog")
ONLINE_RESUME = (
    "text=我的在线简历", "text=在线简历",
    "xpath://*[contains(normalize-space(.), '在线简历')]",
)
KNOWN_POPUP_CLOSE = (
    "css:.dialog-wrap .close", "css:.boss-popup__close",
    "css:.dialog-container .dialog-close"
)
CLOSED_MARKERS = ("text:职位已关闭", "text:职位不存在", "text:停止招聘")

# 聊天列表只处理带可见红点/数字的会话。不同版本的 BOSS 页面类名可能变化，
# 因此保留多个候选，但 ChatMonitor 仍会检查正尺寸并向上定位会话容器。
CHAT_UNREAD_BADGES = (
    "css:.conversation-item [class*='unread']",
    "css:.chat-list-item [class*='unread']",
    "css:[class*='friend'] [class*='badge']",
    "css:[class*='conversation'] [class*='badge']",
    "css:[class*='item'] .red-dot",
)
CHAT_CONVERSATION_ITEMS = (
    "css:.conversation-item",
    "css:.chat-list-item",
    "css:[class*='friend-item']",
    "css:[class*='conversation-item']",
)
CHAT_MESSAGE_ITEMS = (
    "css:.message-item",
    "css:.chat-message",
    "css:[class*='message-item']",
    "css:[class*='message-content']",
)
CHAT_JOB_INFO = (
    "css:[class*='job-info']",
    "css:[class*='position-info']",
    "css:[class*='job-card']",
)
CHAT_RESUME_BUTTON = (
    "xpath://*[self::button or self::a or self::span][normalize-space(.)='发简历']",
    "css:.btn-resume", "css:[class*='send-resume']", "css:[class*='resume-btn']",
)
CHAT_RESUME_OPTIONS = (
    "css:[class*='resume-item']", "css:[class*='resume-card']",
    "css:.dialog-resume-item", "css:[class*='resume-list'] > *",
)
CHAT_RESUME_CONFIRM = (
    "xpath://*[self::button or self::a or self::span][normalize-space(.)='发送']",
    "xpath://*[self::button or self::a or self::span][normalize-space(.)='确定']",
)
