from datetime import date, datetime
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from daily_reports import DailyReportSender, is_due, report_filenames, scheduled_time_for


class ScheduleTests(TestCase):
    def test_weekday_schedule(self):
        self.assertEqual(scheduled_time_for(date(2026, 9, 16)).isoformat(), "20:00:00")
        self.assertFalse(is_due(datetime(2026, 9, 16, 19, 59, tzinfo=ZoneInfo("Asia/Shanghai"))))
        self.assertTrue(is_due(datetime(2026, 9, 16, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))))

    def test_saturday_and_sunday(self):
        self.assertEqual(scheduled_time_for(date(2026, 9, 19)).isoformat(), "18:00:00")
        self.assertTrue(is_due(datetime(2026, 9, 19, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))))
        self.assertIsNone(scheduled_time_for(date(2026, 9, 20)))
        self.assertFalse(is_due(datetime(2026, 9, 20, 23, 59, tzinfo=ZoneInfo("Asia/Shanghai"))))

    def test_exact_filenames(self):
        self.assertEqual(report_filenames(date(2026, 9, 16)), {
            "detail": "2026-09-16_当日人事信息数据同步_详细版.txt",
            "summary": "2026-09-16_当日人事信息数据同步_无明细版.txt",
        })


class MemoryState:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class FakeClient:
    def __init__(self):
        self.me = type("User", (), {"id": 1, "username": "oiyr90557"})()
        self.send_file = AsyncMock(side_effect=[
            type("Message", (), {"id": 101})(),
            type("Message", (), {"id": 102})(),
        ])

    async def get_me(self):
        return self.me


class SendingTests(IsolatedAsyncioTestCase):
    async def test_waits_for_both_files(self):
        sender = DailyReportSender(FakeClient(), MemoryState(), folder_id="folder",
                                   recipient_username="oiyr90557")
        names = report_filenames(date(2026, 9, 16))
        with patch.object(sender, "_find_reports", return_value=(names, {}, None, {})):
            self.assertFalse(await sender.send_for_day(date(2026, 9, 16)))
        sender.client.send_file.assert_not_awaited()

    async def test_sends_each_file_once_and_uses_saved_messages_for_login_account(self):
        state = MemoryState()
        client = FakeClient()
        sender = DailyReportSender(client, state, folder_id="folder",
                                   recipient_username="@oiyr90557")
        names = report_filenames(date(2026, 9, 16))
        found = {
            name: {"id": variant, "name": name, "mimeType": "text/plain"}
            for variant, name in names.items()
        }
        with patch.object(sender, "_find_reports", return_value=(names, found, None, {})), \
                patch.object(sender, "_download", return_value=None):
            self.assertTrue(await sender.send_for_day(date(2026, 9, 16)))
            self.assertTrue(await sender.send_for_day(date(2026, 9, 16)))

        self.assertEqual(client.send_file.await_count, 2)
        self.assertTrue(all(call.args[0] is client.me for call in client.send_file.await_args_list))
        self.assertEqual(state.get("2026-09-16")["status"], "sent")

    async def test_does_not_repeat_uncertain_send(self):
        state = MemoryState()
        names = report_filenames(date(2026, 9, 16))
        state.set("2026-09-16", {
            "status": "sending",
            "sent": {"detail": {"status": "sending", "filename": names["detail"]}},
        })
        client = FakeClient()
        sender = DailyReportSender(client, state, folder_id="folder",
                                   recipient_username="oiyr90557")
        found = {
            name: {"id": variant, "name": name, "mimeType": "text/plain"}
            for variant, name in names.items()
        }
        with patch.object(sender, "_find_reports", return_value=(names, found, None, {})), \
                patch.object(sender, "_download", return_value=None):
            self.assertFalse(await sender.send_for_day(date(2026, 9, 16)))

        self.assertEqual(client.send_file.await_count, 1)
        self.assertEqual(state.get("2026-09-16")["status"], "needs_review")
