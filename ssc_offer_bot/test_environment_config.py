import importlib
import os
import sys
import types
from unittest import TestCase


os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "test-only")
os.environ.pop("TG_SESSION_NAME", None)
os.environ.setdefault("EXPECTED_SSC_USER_ID", "9001")
os.environ.setdefault("TEST_GROUP_HRBP", "-201")
os.environ.setdefault("TEST_GROUP_LEADERSHIP", "-202")
os.environ.setdefault("TEST_GROUP_RECRUIT", "-203")
os.environ.setdefault("TEST_GROUP_TRIGGER", "-204")
os.environ.setdefault("TEST_GROUP_ANNIVERSARY_ACFAN", "-205")
os.environ.setdefault("TEST_GROUP_ANNIVERSARY_OPS1", "-206")
os.environ.setdefault("TEST_GROUP_ANNIVERSARY_OPS2", "-207")
os.environ.setdefault("TEST_GROUP_ANNIVERSARY_CHANNEL", "-208")
os.environ.setdefault("TEST_GROUP_ANNIVERSARY_TECH", "-209")
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))

prod = importlib.import_module("config_prod")
test = importlib.import_module("config_test")


class EnvironmentConfigTests(TestCase):
    def test_source_and_target_groups_are_separate(self):
        self.assertEqual(test.GROUP_REGULARIZATION_TRIGGER, -204)
        self.assertNotEqual(prod.GROUP_REGULARIZATION_TRIGGER, test.GROUP_REGULARIZATION_TRIGGER)
        self.assertNotIn(test.GROUP_LEADERSHIP, {
            prod.GROUP_LEADERSHIP, prod.GROUP_RECRUIT,
            *(rule["chat_id"] for rule in prod.ANNIVERSARY_GROUP_RULES),
        })

    def test_all_anniversary_destinations_match_drive_configuration(self):
        self.assertEqual(
            {rule["chat_id"] for rule in test.ANNIVERSARY_GROUP_RULES},
            {-205, -206, -207, -208, -209},
        )

    def test_approval_codes_cannot_be_consumed_by_both_instances(self):
        self.assertTrue({"1", "2", "3"}.isdisjoint(test.APPROVAL_CODES))
        self.assertEqual(test.REGULARIZATION_APPROVAL_CODE, "测试2")
        self.assertEqual(test.ANNIVERSARY_APPROVAL_CODE, "测试3")

    def test_sessions_and_runtime_state_are_separate(self):
        self.assertNotEqual(prod.SESSION_NAME, test.SESSION_NAME)
        self.assertNotEqual(prod.DB_PATH, test.DB_PATH)
        self.assertFalse(test.DAILY_REPORT_ENABLED)
        self.assertFalse(test.HRGS_FORWARD_ENABLED)

    def test_only_test_environment_allows_manual_trigger_messages(self):
        os.environ["BOT_ENV"] = "test"
        selected = importlib.import_module("config")
        selected = importlib.reload(selected)
        self.assertTrue(selected.ALLOW_MANUAL_TRIGGERS)
        os.environ["BOT_ENV"] = "prod"
        selected = importlib.reload(selected)
        self.assertFalse(selected.ALLOW_MANUAL_TRIGGERS)

    def test_same_expected_ssc_account_is_enforced(self):
        self.assertEqual(int(os.environ["EXPECTED_SSC_USER_ID"]), 9001)

    def test_loader_selects_requested_environment(self):
        os.environ["BOT_ENV"] = "test"
        selected = importlib.import_module("config")
        selected = importlib.reload(selected)
        self.assertEqual(selected.ENVIRONMENT, "test")
        self.assertEqual(selected.GROUP_LEADERSHIP, -202)
        os.environ["BOT_ENV"] = "prod"
        selected = importlib.reload(selected)
        self.assertEqual(selected.ENVIRONMENT, "prod")
        self.assertEqual(selected.GROUP_LEADERSHIP, prod.GROUP_LEADERSHIP)
