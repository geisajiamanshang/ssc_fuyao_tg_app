# -*- coding: utf-8 -*-
"""定时从 Google Drive 下载当日人事同步文件并发送给 SSC。"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("ssc_offer_bot.daily_reports")
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"


def report_filenames(day):
    """返回详细版、无明细版的精确文件名。"""
    prefix = day.isoformat()
    return {
        "detail": f"{prefix}_当日人事信息数据同步_详细版.txt",
        "summary": f"{prefix}_当日人事信息数据同步_无明细版.txt",
    }


def scheduled_time_for(day):
    """周一至周五 20:00，周六 18:00，周日不执行。"""
    if day.weekday() <= 4:
        return time(20, 0)
    if day.weekday() == 5:
        return time(18, 0)
    return None


def is_due(now):
    scheduled = scheduled_time_for(now.date())
    return scheduled is not None and now.time().replace(tzinfo=None) >= scheduled


def _drive_session():
    """优先用服务账号；公开文件夹也可使用 Google Drive API key。"""
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if credentials_path:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=[DRIVE_SCOPE]
        )
        return AuthorizedSession(credentials), {}

    api_key = os.environ.get("GOOGLE_DRIVE_API_KEY", "").strip()
    if api_key:
        import requests

        return requests.Session(), {"key": api_key}

    raise RuntimeError(
        "未配置 Google Drive 凭证：请设置 GOOGLE_APPLICATION_CREDENTIALS "
        "或 GOOGLE_DRIVE_API_KEY"
    )


class DailyReportSender:
    def __init__(self, client, state, *, folder_id, recipient_username,
                 timezone="Asia/Shanghai", poll_seconds=300):
        self.client = client
        self.state = state
        self.folder_id = folder_id
        self.recipient_username = recipient_username.strip().lstrip("@")
        self.timezone = ZoneInfo(timezone)
        self.poll_seconds = max(30, int(poll_seconds))
        self._recipient = None

    async def _resolve_recipient(self):
        if self._recipient is not None:
            return self._recipient
        me = await self.client.get_me()
        actual = (getattr(me, "username", "") or "").casefold()
        expected = self.recipient_username.casefold()
        if actual == expected:
            # 给当前登录账号发送即 Telegram 收藏夹。
            self._recipient = me
            return me

        recipient = await self.client.get_entity(self.recipient_username)
        resolved = (getattr(recipient, "username", "") or "").casefold()
        if resolved != expected:
            raise RuntimeError(f"无法确认日报收件人 @{self.recipient_username}")
        self._recipient = recipient
        return recipient

    def _find_reports(self, day):
        session, auth_params = _drive_session()
        names = report_filenames(day)
        escaped_folder = self.folder_id.replace("'", "\\'")
        name_query = " or ".join(
            f"name = '{name.replace(chr(39), chr(92) + chr(39))}'"
            for name in names.values()
        )
        params = {
            **auth_params,
            "q": f"'{escaped_folder}' in parents and trashed = false and ({name_query})",
            "fields": "files(id,name,mimeType,createdTime,modifiedTime,size)",
            "orderBy": "modifiedTime desc",
            "pageSize": 20,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        wanted = set(names.values())
        found = {}
        for item in response.json().get("files", []):
            if item.get("name") in wanted and item["name"] not in found:
                found[item["name"]] = item
        return names, found, session, auth_params

    @staticmethod
    def _download(session, auth_params, drive_file, destination):
        mime_type = drive_file.get("mimeType", "")
        if mime_type.startswith("application/vnd.google-apps"):
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}/export"
            params = {**auth_params, "mimeType": "text/plain"}
        else:
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}"
            params = {**auth_params, "alt": "media"}
        with session.get(url, params=params, timeout=120, stream=True) as response:
            response.raise_for_status()
            with open(destination, "wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)

    async def send_for_day(self, day):
        """两份文件都存在时发送尚未成功发送的文件。"""
        key = day.isoformat()
        record = self.state.get(key) or {}
        if record.get("status") == "sent":
            return True

        names, found, session, auth_params = await asyncio.to_thread(
            self._find_reports, day
        )
        missing = [name for name in names.values() if name not in found]
        if missing:
            log.info("[人事日报] %s 文件尚未齐全：%s", key, "、".join(missing))
            return False

        recipient = await self._resolve_recipient()
        sent = dict(record.get("sent", {}))
        with tempfile.TemporaryDirectory(prefix="ssc-daily-report-") as temp_dir:
            for variant in ("detail", "summary"):
                variant_status = sent.get(variant, {}).get("status")
                if variant_status == "sent":
                    continue
                if variant_status == "sending":
                    log.error(
                        "[人事日报] %s 上次发送结果不确定，为避免重复发送已暂停该文件；请人工核查",
                        sent[variant].get("filename", names[variant]),
                    )
                    continue
                filename = names[variant]
                drive_file = found[filename]
                destination = Path(temp_dir) / filename
                await asyncio.to_thread(
                    self._download, session, auth_params, drive_file, destination
                )
                sent[variant] = {
                    "status": "sending",
                    "file_id": drive_file["id"],
                    "filename": filename,
                }
                self.state.set(key, {"status": "sending", "sent": sent})
                message = await self.client.send_file(
                    recipient, str(destination), force_document=True
                )
                sent[variant] = {
                    "status": "sent",
                    "file_id": drive_file["id"],
                    "filename": filename,
                    "message_id": message.id,
                }
                self.state.set(key, {"status": "sending", "sent": sent})
                log.info("[人事日报] %s 已发送给@%s", filename, self.recipient_username)

        completed = all(
            sent.get(variant, {}).get("status") == "sent"
            for variant in ("detail", "summary")
        )
        self.state.set(key, {
            "status": "sent" if completed else "needs_review",
            "sent": sent,
        })
        return completed

    async def run(self):
        log.info(
            "[人事日报] 定时任务启动：周一至周五20:00、周六18:00（%s），收件人@%s",
            self.timezone.key, self.recipient_username,
        )
        while True:
            try:
                now = datetime.now(self.timezone)
                if is_due(now):
                    await self.send_for_day(now.date())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[人事日报] 检查或发送失败，将在下一轮重试")
            await asyncio.sleep(self.poll_seconds)
