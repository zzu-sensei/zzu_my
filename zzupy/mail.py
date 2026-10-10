"""邮件发送模块。

该模块只依赖 ``httpx2``，不引入 SMTP 与额外第三方库，便于在 Vercel 等
Serverless 运行环境中直接调用。所有发送逻辑都基于 HTTP 发信 API：

- ``resend``：[Resend](https://resend.com) ``POST https://api.resend.com/emails``
- ``brevo``：[Brevo](https://brevo.com) ``POST https://api.brevo.com/v3/smtp/email``

两家服务都只需要在你的域名上配置 SPF / DKIM 的 DNS 记录即可用自有域名发信，
不需要真实的域名邮箱，也不需要 MX 记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping

import httpx2

from zzupy.logging import build_http_event_hooks, logger

MailProvider = Literal["resend", "brevo"]

RESEND_ENDPOINT: Final = "https://api.resend.com/emails"
BREVO_ENDPOINT: Final = "https://api.brevo.com/v3/smtp/email"

PROVIDER_ENDPOINTS: Final[dict[str, str]] = {
    "resend": RESEND_ENDPOINT,
    "brevo": BREVO_ENDPOINT,
}

DEFAULT_SENDER_NAME: Final = "郑大生活助手"
DEFAULT_TIMEOUT: Final = 15.0

#: 这些状态码代表请求本身有问题，重试或换服务商都不会成功。
FATAL_STATUS_CODES: Final[frozenset[int]] = frozenset({400, 401, 403, 404, 422})


class MailError(Exception):
    """邮件相关错误的基类。"""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message


class MailConfigError(MailError):
    """邮件配置不完整或不合法。

    这类错误说明环境变量没配对，不应该重试。
    """


class MailSendError(MailError):
    """调用发信 API 失败。"""


@dataclass(frozen=True)
class MailConfig:
    """一次发信所需的全部配置。

    Args:
        provider: 发信服务商，``resend`` 或 ``brevo``。
        api_key: 服务商控制台生成的 API Key。
        sender: 发信地址。必须是已经在该服务商验证过的域名下的地址。
        sender_name: 发信人显示名。
        recipients: 收件人地址列表。
        fallback_provider: 主服务商失败时改用的备用服务商。
        fallback_api_key: 备用服务商的 API Key。
    """

    provider: MailProvider
    api_key: str
    sender: str
    recipients: tuple[str, ...] = ()
    sender_name: str = DEFAULT_SENDER_NAME
    fallback_provider: MailProvider | None = None
    fallback_api_key: str = ""
    timeout: float = DEFAULT_TIMEOUT

    def validate(self) -> None:
        """校验配置完整性。

        Raises:
            MailConfigError: 任一必填项缺失或服务商无法识别。
        """
        if self.provider not in PROVIDER_ENDPOINTS:
            raise MailConfigError(
                f"不支持的发信服务商：{self.provider}",
                provider=self.provider,
                context={"supported": sorted(PROVIDER_ENDPOINTS)},
            )
        if not self.api_key.strip():
            raise MailConfigError("缺少发信 API Key", provider=self.provider)
        if "@" not in self.sender:
            raise MailConfigError(
                f"发信地址不合法：{self.sender!r}",
                provider=self.provider,
            )
        if not self.recipients:
            raise MailConfigError("缺少收件人地址", provider=self.provider)
        for recipient in self.recipients:
            if "@" not in recipient:
                raise MailConfigError(
                    f"收件人地址不合法：{recipient!r}",
                    provider=self.provider,
                )
        if self.fallback_provider is not None:
            if self.fallback_provider not in PROVIDER_ENDPOINTS:
                raise MailConfigError(
                    f"不支持的备用服务商：{self.fallback_provider}",
                    provider=self.provider,
                )
            if not self.fallback_api_key.strip():
                raise MailConfigError(
                    "配置了备用服务商但缺少其 API Key",
                    provider=self.provider,
                )


@dataclass(frozen=True)
class MailMessage:
    """一封待发送的邮件。

    Args:
        subject: 邮件主题。
        text: 纯文本正文。
        html: HTML 正文，留空时由服务商按纯文本渲染。
    """

    subject: str
    text: str
    html: str = ""

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise MailConfigError("邮件主题不能为空")
        if not self.text.strip() and not self.html.strip():
            raise MailConfigError("邮件正文不能为空")


@dataclass(frozen=True)
class MailResult:
    """一次成功发信的结果。

    Args:
        provider: 实际生效的服务商，可能不是配置里的主服务商。
        message_id: 服务商返回的消息 ID。
        attempts: 记录每个尝试过的服务商的错误信息。
    """

    provider: str
    message_id: str
    attempts: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _resend_payload(config: MailConfig, message: MailMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "from": f"{config.sender_name} <{config.sender}>",
        "to": list(config.recipients),
        "subject": message.subject,
        "text": message.text,
    }
    if message.html.strip():
        payload["html"] = message.html
    return payload


def _brevo_payload(config: MailConfig, message: MailMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sender": {"email": config.sender, "name": config.sender_name},
        "to": [{"email": address} for address in config.recipients],
        "subject": message.subject,
        "textContent": message.text,
    }
    if message.html.strip():
        payload["htmlContent"] = message.html
    return payload


def _send_with_provider(
    provider: MailProvider,
    api_key: str,
    config: MailConfig,
    message: MailMessage,
    client: httpx2.Client,
) -> str:
    """用指定服务商发送一次邮件，返回消息 ID。

    Raises:
        MailSendError: 请求失败或服务商返回错误。
    """
    if provider == "resend":
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = _resend_payload(config, message)
    else:
        headers = {"api-key": api_key}
        payload = _brevo_payload(config, message)

    endpoint = PROVIDER_ENDPOINTS[provider]
    logger.debug("正在通过 {} 发送邮件到 {}", provider, list(config.recipients))

    try:
        response = client.post(endpoint, headers=headers, json=payload)
    except httpx2.RequestError as exc:
        logger.error("{} 发信网络请求失败: {}", provider, exc)
        raise MailSendError(
            f"{provider} 网络请求失败",
            provider=provider,
            context={"cause_type": type(exc).__name__},
        ) from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        logger.error("{} 发信返回 {}: {}", provider, response.status_code, detail)
        raise MailSendError(
            f"{provider} 返回 {response.status_code}",
            provider=provider,
            context={"status_code": response.status_code, "detail": detail},
        )

    try:
        data = response.json()
    except ValueError:
        # 有的服务商在成功时返回空体，此时不影响发信结果。
        logger.debug("{} 发信响应不是 JSON，按成功处理", provider)
        data = {}

    message_id = str(data.get("id") or data.get("messageId") or "")
    logger.info("已通过 {} 发送邮件，messageId={}", provider, message_id or "(未知)")
    return message_id


def send_mail(
    config: MailConfig,
    message: MailMessage,
    *,
    client: httpx2.Client | None = None,
) -> MailResult:
    """发送一封邮件，主服务商失败时自动尝试备用服务商。

    Args:
        config: 发信配置。
        message: 邮件内容。
        client: 可选的 ``httpx2.Client``，便于复用连接池或注入测试替身。

    Returns:
        发信结果，``provider`` 表示实际生效的服务商。

    Raises:
        MailConfigError: 配置不完整。
        MailSendError: 所有可用服务商都发送失败。
    """
    config.validate()

    owns_client = client is None
    active = client or httpx2.Client(
        timeout=config.timeout,
        event_hooks=build_http_event_hooks(),
    )

    candidates: list[tuple[MailProvider, str]] = [(config.provider, config.api_key)]
    if config.fallback_provider is not None:
        candidates.append((config.fallback_provider, config.fallback_api_key))

    attempts: list[dict[str, Any]] = []
    try:
        for index, (provider, api_key) in enumerate(candidates):
            try:
                message_id = _send_with_provider(
                    provider, api_key, config, message, active
                )
            except MailSendError as exc:
                attempts.append(
                    {"provider": provider, "message": exc.message, **exc.context}
                )
                is_last = index == len(candidates) - 1
                status = exc.context.get("status_code")
                if is_last or status in FATAL_STATUS_CODES:
                    raise
                logger.warning("{} 发信失败，改用备用服务商重试", provider)
                continue
            return MailResult(
                provider=provider,
                message_id=message_id,
                attempts=tuple(attempts),
            )
    finally:
        if owns_client:
            active.close()

    # 正常情况下上面的循环要么返回结果，要么抛出异常。
    raise MailSendError(
        "没有可用的发信服务商",
        provider=config.provider,
        context={"attempts": attempts},
    )


__all__ = [
    "BREVO_ENDPOINT",
    "MailConfig",
    "MailConfigError",
    "MailError",
    "MailMessage",
    "MailProvider",
    "MailResult",
    "MailSendError",
    "PROVIDER_ENDPOINTS",
    "RESEND_ENDPOINT",
    "send_mail",
]
