"""Email sending: Resend HTTP API when RESEND_API_KEY is set, SMTP
(mailcatcher) otherwise — dev behavior unchanged.

Failures are logged, not raised — callers run this in BackgroundTasks.
"""
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10.0


def _send_via_resend(*, to: str, subject: str, html: str) -> None:
    response = httpx.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={
            "from": settings.email_from,
            "to": [to],
            "subject": subject,
            "html": html,
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _send_via_smtp(*, to: str, subject: str, html: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("Este mensaje requiere un cliente compatible con HTML.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_TLS and settings.SMTP_PORT != 1025:
            smtp.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def send_email(*, to: str, subject: str, html: str) -> None:
    try:
        if settings.use_resend:
            _send_via_resend(to=to, subject=subject, html=html)
        else:
            _send_via_smtp(to=to, subject=subject, html=html)
        logger.info("email sent to=%s subject=%s", to, subject)
    except Exception:
        logger.exception("email send failed to=%s subject=%s", to, subject)
