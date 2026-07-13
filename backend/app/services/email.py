"""Email sending: Resend in production, SMTP (mailcatcher) locally.

Failures are logged, not raised — callers run this in BackgroundTasks.
"""
import logging
import smtplib
from email.message import EmailMessage

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(*, to: str, subject: str, html: str) -> None:
    try:
        if settings.use_resend:
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send(
                {
                    "from": f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>",
                    "to": [to],
                    "subject": subject,
                    "html": html,
                }
            )
        else:
            msg = EmailMessage()
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
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
        logger.info("email sent to=%s subject=%s", to, subject)
    except Exception:
        logger.exception("email send failed to=%s subject=%s", to, subject)
