# -*- coding: utf-8 -*-
"""测试环境配置。不得从生产配置继承任何群组或审批人。"""

import os

from config_common import *


SESSION_NAME = os.environ.get("TG_SESSION_NAME", "ssc_offer_bot_test")

GROUP_HRBP = -5447064641
GROUP_LEADERSHIP = -5365249364
GROUP_RECRUIT = -5577108580
GROUP_REGULARIZATION_TRIGGER = -5339407017
GROUP_ANNIVERSARY_TRIGGER = GROUP_REGULARIZATION_TRIGGER
GROUP_REGULARIZATION_SYNC = -5258992607

LEADER_FIRST = "haok001"
LEADER_SECOND_TECH = "haok001"
LEADER_FINAL = "Zoey95274"

ANNIVERSARY_GROUP_RULES = [
    {"name": "测试-ACFAN", "keywords": ["ACFAN特战队", "ACFAN", "AIGC原创部", "AIGC"], "chat_id": -5375721803},
    {"name": "测试-运营一部", "keywords": ["运营一部", "运营1部"], "chat_id": -5479404347},
    {"name": "测试-运营二部", "keywords": ["运营二部", "运营2部"], "chat_id": -5145693025},
    {"name": "测试-渠道商务", "keywords": ["渠道部", "商务部", "渠道商务部"], "chat_id": -1004345123072},
    {"name": "测试-技术效能", "keywords": ["技术部", "效能部", "技术效能部", "技术中心", "研发部"], "chat_id": -5412973830},
]

# 与生产实例共用收藏夹时，测试审批码必须带前缀，避免两套实例抢单。
OFFER_APPROVAL_CODE = "测试1"
REGULARIZATION_APPROVAL_CODE = "测试2"
ANNIVERSARY_APPROVAL_CODE = "测试3"
APPROVAL_CODES = frozenset({
    OFFER_APPROVAL_CODE, REGULARIZATION_APPROVAL_CODE, ANNIVERSARY_APPROVAL_CODE,
})
DAILY_REPORT_ENABLED = False
HRGS_FORWARD_ENABLED = False

REGULARIZATION_OUTPUT_FOLDER_ID = os.environ.get("TEST_REGULARIZATION_OUTPUT_FOLDER_ID", REGULARIZATION_OUTPUT_FOLDER_ID)
ANNIVERSARY_DRIVE_ROOT_ID = os.environ.get("TEST_ANNIVERSARY_DRIVE_ROOT_ID", ANNIVERSARY_DRIVE_ROOT_ID)

DB_PATH = "offer_state.test.json"
DAILY_REPORT_STATE_PATH = DB_PATH + ".daily_reports.json"
REGULARIZATION_STATE_PATH = DB_PATH + ".regularization.json"
ANNIVERSARY_STATE_PATH = DB_PATH + ".anniversary.json"
LOG_PATH = "bot.test.log"
