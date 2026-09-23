# -*- coding: utf-8 -*-
"""按 BOT_ENV 加载测试或生产配置，并在启动前执行防误发检查。"""

import importlib
import os

from dotenv import load_dotenv


# 默认 test 是故意的：漏配 BOT_ENV 时宁可启动失败，也不能误发生产群。
_environment = os.environ.get("BOT_ENV", "test").strip().casefold()
if _environment not in {"test", "prod"}:
    raise RuntimeError("BOT_ENV 只能是 test 或 prod")

_env_file = os.path.join(os.path.dirname(__file__), f".env.{_environment}")
load_dotenv(_env_file, override=False)
os.environ["BOT_ENV"] = _environment

_profile = importlib.import_module(f"config_{_environment}")
for _name in dir(_profile):
    if _name.isupper():
        globals()[_name] = getattr(_profile, _name)

ENVIRONMENT = _environment
OFFER_APPROVAL_CODE = "测试1" if ENVIRONMENT == "test" else "1"
REGULARIZATION_APPROVAL_CODE = "测试2" if ENVIRONMENT == "test" else "2"
ANNIVERSARY_APPROVAL_CODE = "测试3" if ENVIRONMENT == "test" else "3"
REGULARIZATION_TODAY_APPROVAL_CODE = "测试4" if ENVIRONMENT == "test" else "4"
REGULARIZATION_TODAY_SYNC_APPROVAL_CODE = "测试4.1" if ENVIRONMENT == "test" else "4.1"
# 入职确认发布到联合管理群后，再次经收藏夹审批转发到预入职登记群。
PRE_ONBOARDING_APPROVAL_CODE = "测试11" if ENVIRONMENT == "test" else "11"
# 转正倒数4天提醒触发后，员工本人的转正申请单独走这个审批码放行到联合管理工作群；
# 与预转正提醒的审批码（2）并存、互不影响，SSC可在收藏夹改完内容再批准。
REGULARIZATION_APPLICATION_APPROVAL_CODE = "测试21" if ENVIRONMENT == "test" else "21"
APPROVAL_CODES = frozenset({
    OFFER_APPROVAL_CODE,
    REGULARIZATION_APPROVAL_CODE,
    ANNIVERSARY_APPROVAL_CODE,
    REGULARIZATION_TODAY_APPROVAL_CODE,
    REGULARIZATION_TODAY_SYNC_APPROVAL_CODE,
    PRE_ONBOARDING_APPROVAL_CODE,
    REGULARIZATION_APPLICATION_APPROVAL_CODE,
})
DAILY_REPORT_ENABLED = ENVIRONMENT == "prod"
HRGS_FORWARD_ENABLED = ENVIRONMENT == "prod"
# 预入职登记群ID尚未在该环境配置完成前自动跳过，不报错也不误发。
PRE_ONBOARDING_FORWARD_ENABLED = bool(GROUP_PRE_ONBOARDING)
# 生产只接受指定机器人的提醒；测试群允许SSC人工粘贴提醒做联调。
ALLOW_MANUAL_TRIGGERS = ENVIRONMENT == "test"
# GROUP_REGULARIZATION_SYNC / GROUP_PRE_ONBOARDING 未来若在某环境留空（None），
# 下面的条件不会把它们计入白名单。
ALLOWED_DESTINATION_IDS = frozenset({
    GROUP_LEADERSHIP,
    GROUP_RECRUIT,
    *(rule["chat_id"] for rule in ANNIVERSARY_GROUP_RULES),
    *([GROUP_REGULARIZATION_SYNC] if GROUP_REGULARIZATION_SYNC else []),
    *([GROUP_PRE_ONBOARDING] if GROUP_PRE_ONBOARDING else []),
})
# 生产进程即便账号仍留在测试群里，也一律不处理测试群消息。
EXCLUDED_CHAT_IDS = TEST_CHAT_IDS if ENVIRONMENT == "prod" else frozenset()

if ENVIRONMENT == "test":
    _test_chat_ids = ALLOWED_DESTINATION_IDS | {
        GROUP_HRBP,
        GROUP_REGULARIZATION_TRIGGER,
        GROUP_ANNIVERSARY_TRIGGER,
    }
    _unsafe = _test_chat_ids & PRODUCTION_CHAT_IDS
    if _unsafe:
        raise RuntimeError(f"测试环境包含生产群 {_unsafe}，已拒绝启动")

if GROUP_HRBP in ALLOWED_DESTINATION_IDS:
    raise RuntimeError("来源群不能同时成为自动发送目标群")
