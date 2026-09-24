# -*- coding: utf-8 -*-
"""测试与生产共用、且不会决定消息去向的配置。"""

import os


API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "").strip()
EXPECTED_SSC_USER_ID = 8853414240

if not API_ID or not API_HASH:
    raise RuntimeError("当前环境缺少 TG_API_ID / TG_API_HASH")
if not EXPECTED_SSC_USER_ID:
    raise RuntimeError("当前环境缺少 EXPECTED_SSC_USER_ID，拒绝在未知账号下启动")

TECH_CENTER_KEYWORDS = ["技术中心"]

DEPARTMENT_LEADER_TAGS = [
    {
        "org_unit": "技术中心",
        "dept_keywords": ["后端组"],
        "leaders": ["DaBai10010", "chuqianyiding", "liyuanba666", "wean4790"],
    },
    {
        "org_unit": "技术中心",
        "dept_keywords": ["前端组"],
        "leaders": ["DaBai10010", "chuqianyiding", "wdz999", "wean4790"],
    },
    {
        "org_unit": "效能中心",
        "dept_keywords": [""],
        "leaders": ["DaBai10010", "chuqianyiding", "wean4790"],
    },
    {
        "org_unit": "运营中心",
        "dept_keywords": ["运营1部"],
        "leaders": ["DaBai10010", "chuqianyiding", "zlei1216", "wean4790"],
    },
    {
        "org_unit": "运营中心",
        "dept_keywords": ["ACFAN"],
        "leaders": ["DaBai10010", "chuqianyiding", "zlei1216", "wean4790"],
    },
    {
        "org_unit": "运营中心",
        "dept_keywords": ["运营2部"],
        "leaders": ["DaBai10010", "chuqianyiding", "xxs202215cz2025", "wean4790"],
    },
]
DEFAULT_LEADERS = []

DAILY_REPORT_FOLDER_ID = os.environ.get(
    "DAILY_REPORT_FOLDER_ID", "15Jrw7hl6erl2BFDwkqg5gEj_bOLA1dDk"
)
DAILY_REPORT_RECIPIENT = os.environ.get("DAILY_REPORT_RECIPIENT", "oiyr90557")
DAILY_REPORT_TIMEZONE = os.environ.get("DAILY_REPORT_TIMEZONE", "Asia/Shanghai")
DAILY_REPORT_POLL_SECONDS = int(os.environ.get("DAILY_REPORT_POLL_SECONDS", "300"))

REGULARIZATION_TRIGGER_BOT_ID = int(
    os.environ.get("REGULARIZATION_TRIGGER_BOT_ID", "8416618309")
)
REGULARIZATION_TRIGGER_KEYWORD = "转正提醒-恒睿-转正倒数4天"
REGULARIZATION_TODAY_TRIGGER_KEYWORD = "转正提醒-恒睿-今日转正"
REGULARIZATION_OUTPUT_FOLDER_ID = os.environ.get(
    "REGULARIZATION_OUTPUT_FOLDER_ID", "17QEQ5Q1Nyfp1asMiXZYt-4vd4UDHVxAg"
)

ANNIVERSARY_TRIGGER_BOT_ID = REGULARIZATION_TRIGGER_BOT_ID
ANNIVERSARY_TRIGGER_KEYWORDS = ("入职周年提醒", "恒睿")
ANNIVERSARY_DRIVE_ROOT_ID = os.environ.get(
    "ANNIVERSARY_DRIVE_ROOT_ID", "13JH168_QwFcGaboQUrPF2sGnCjbXaa7E"
)
ANNIVERSARY_DRIVE_PATH = ("海报助手", "输出", "当月入职周年海报")

# 新人培训群里 @YYZXpeixun_bot 发的"新人培训考试通过"消息触发；
# 入职助手/输出 文件夹下每个新人一个独立TXT，按TG用户名匹配文件内容。
ONBOARDING_TRAINING_TRIGGER_KEYWORD = "新人培训考试通过"
ONBOARDING_TRAINING_OUTPUT_FOLDER_ID = os.environ.get(
    "ONBOARDING_TRAINING_OUTPUT_FOLDER_ID", "1gAxHM2zalT81_nTOSA5iGHwQSpR_--ia"
)

# SSC3组内部工作沟通群 / 转正提醒来源群里出现"全员群"关键词时，
# 把紧邻的上一条图文通知转发到收藏夹，经审批码7一次性广播到全部全员群。
ALL_STAFF_NOTICE_TRIGGER_KEYWORD = "全员群"

# 洛羽-SSC主管-CN私聊里出现账号申请类关键词后自动生成申请草稿；显示名匹配
# （暂无确认的用户名），后续拿到@用户名可以改成更稳定的用户名匹配。
ACCOUNT_REQUEST_MANAGER_DISPLAY_NAME = "洛羽-SSC主管-CN"

# 恒睿公司-联合管理群出现"劝退申请"/"离职申请"关键词后，按员工姓名在Drive
# 云端 离职助手/输出 文件夹查找该员工的《XX_离职信息同步.txt》。文件夹ID
# 待补充：打开该Drive文件夹，把浏览器地址栏里 folders/ 后面那串ID填到
# .env 的 OFFBOARDING_OUTPUT_FOLDER_ID，留空时功能自动跳过。
OFFBOARDING_OUTPUT_FOLDER_ID = os.environ.get("OFFBOARDING_OUTPUT_FOLDER_ID", "")

# 离职流程 Drive 文件夹（https://drive.google.com/drive/u/1/folders/
# 1A4XavmJ8O6Rf2LUWPkRd17ybgBTPzJwZ），检查其下 当月离职明细 子文件夹里
# 是否已有该员工的《XX_员工离职审批表》。这个文件夹ID是直接给定的，不像
# OFFBOARDING_OUTPUT_FOLDER_ID 那样默认留空，但仍支持用 .env 覆盖。
OFFBOARDING_PROCESS_FOLDER_ID = os.environ.get(
    "OFFBOARDING_PROCESS_FOLDER_ID", "1A4XavmJ8O6Rf2LUWPkRd17ybgBTPzJwZ"
)

# 离职信息同步文件 / 员工离职审批表在Drive中暂未找到时，不算失败，每隔
# 这么多秒重新查询一次直到找到为止（与新人培训/日报等一次性判定的场景
# 不同——离职资料本来就可能滞后上传）。
OFFBOARDING_RETRY_POLL_SECONDS = int(
    os.environ.get("OFFBOARDING_RETRY_POLL_SECONDS", "300")
)

# 测试环境启动时会检查所有可发送目标不属于这些生产群。
PRODUCTION_CHAT_IDS = frozenset({
    -1003559652510,  # HRBP沟通群
    -1003865890708,  # 联合管理群
    -1004380831613,  # 招聘群
    -1004492520637,  # 云昭触发群
    -1003553653887,  # ACFAN全员群
    -1003663263859,  # 运营一部全员群
    -1003950803307,  # 运营二部全员群
    -1003872014182,  # 渠道/商务部全员群
    -1003946619557,  # 技术/效能部全员群
    -1004334431069,  # 工作帐号需求群-SSC3组
    -5164874973,  # 北斗离职人员-同步商务中心群
})

# 生产环境启动时用于屏蔽这些测试群消息，避免账号同时留在两边时误处理。
TEST_CHAT_IDS = frozenset({
    -5447064641,  # 测试-HRBP沟通群
    -5365249364,  # 测试-联合管理群
    -5577108580,  # 测试-招聘群
    -5339407017,  # 测试-转正/周年触发群
    -5375721803,  # 测试-ACFAN全员群
    -5479404347,  # 测试-运营一部全员群
    -5145693025,  # 测试-运营二部全员群
    -1004345123072,  # 测试-渠道商务全员群
    -5412973830,  # 测试-技术效能全员群
})

# Offer审批链（场景二）里，领导除了回复文字，也可以直接在@他的审批提示消息
# 上点这些表情作为同意；沿用parsers.is_approval里认可的"👌"，不额外放宽。
APPROVAL_REACTION_EMOJIS = frozenset({"👌"})
