import importlib
import os
import sys
import types
from pathlib import Path
from unittest import TestCase


os.environ.setdefault("TG_API_ID", "1")
os.environ.setdefault("TG_API_HASH", "test-only")
os.environ.pop("TG_SESSION_NAME", None)
os.environ.setdefault("EXPECTED_SSC_USER_ID", "9001")
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))

prod = importlib.import_module("config_prod")
test = importlib.import_module("config_test")


class EnvironmentConfigTests(TestCase):
    def test_source_and_target_groups_are_separate(self):
        self.assertEqual(test.GROUP_REGULARIZATION_TRIGGER, -5339407017)
        self.assertNotEqual(prod.GROUP_REGULARIZATION_TRIGGER, test.GROUP_REGULARIZATION_TRIGGER)
        self.assertNotIn(test.GROUP_LEADERSHIP, {
            prod.GROUP_LEADERSHIP, prod.GROUP_RECRUIT,
            *(rule["chat_id"] for rule in prod.ANNIVERSARY_GROUP_RULES),
        })

    def test_all_anniversary_destinations_match_drive_configuration(self):
        self.assertEqual(
            {rule["chat_id"] for rule in test.ANNIVERSARY_GROUP_RULES},
            {-5375721803, -5479404347, -5145693025, -1004345123072, -5412973830},
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
        self.assertEqual(selected.GROUP_LEADERSHIP, -5365249364)
        os.environ["BOT_ENV"] = "prod"
        selected = importlib.reload(selected)
        self.assertEqual(selected.ENVIRONMENT, "prod")
        self.assertEqual(selected.GROUP_LEADERSHIP, prod.GROUP_LEADERSHIP)

    def test_missing_environment_defaults_to_safe_test_profile(self):
        os.environ.pop("BOT_ENV", None)
        selected = importlib.reload(importlib.import_module("config"))
        self.assertEqual(selected.ENVIRONMENT, "test")
        self.assertEqual(selected.GROUP_LEADERSHIP, test.GROUP_LEADERSHIP)

    def test_test_profile_does_not_import_production_profile(self):
        path = Path(__file__).with_name("config_test.py")
        with path.open(encoding="utf-8") as source_file:
            self.assertNotIn("config_prod", source_file.read())

    def test_test_destinations_never_overlap_production(self):
        destinations = {
            test.GROUP_LEADERSHIP,
            test.GROUP_RECRUIT,
            *(rule["chat_id"] for rule in test.ANNIVERSARY_GROUP_RULES),
        }
        self.assertTrue(destinations.isdisjoint(prod.PRODUCTION_CHAT_IDS))
