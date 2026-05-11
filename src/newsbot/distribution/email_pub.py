"""EmailPublisher — Send the report as an HTML email via Gmail SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from newsbot.distribution.base import BasePublisher
from newsbot.formatting.email import format_email_html
from newsbot.models import Report

logger = logging.getLogger(__name__)

_GMAIL_SMTP_HOST = "smtp.gmail.com"
_GMAIL_SMTP_PORT = 587


class EmailPublisher(BasePublisher):
    def __init__(
        self,
        gmail_address: str,
        app_password: str,
        recipients: list[str],
        dry_run: bool = False,
    ) -> None:
        self._gmail_address = gmail_address
        self._app_password = app_password
        self._recipients = [r.strip() for r in recipients if r.strip()]
        self._dry_run = dry_run

    @property
    def channel_name(self) -> str:
        return "email"

    def publish(self, report: Report) -> bool:
        if self._dry_run:
            self._log_dry_run(report)
            logger.info("[DRY_RUN][email] would send to %s", self._recipients)
            return True

        if not self._recipients:
            logger.warning("[email] no recipients configured, skipping")
            return False

        html = format_email_html(report)
        subject = f"[AI뉴스] {report.headline}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._gmail_address
        msg["To"] = ", ".join(self._recipients)
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            with smtplib.SMTP(_GMAIL_SMTP_HOST, _GMAIL_SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self._gmail_address, self._app_password)
                smtp.sendmail(self._gmail_address, self._recipients, msg.as_string())

            logger.info("[email] sent report %s to %d recipients", report.report_id, len(self._recipients))
            self._log_published(report)
            return True

        except smtplib.SMTPException as exc:
            logger.error("[email] SMTP error: %s", exc)
            raise
