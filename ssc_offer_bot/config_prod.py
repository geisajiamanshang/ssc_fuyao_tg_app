# -*- coding: utf-8 -*-
"""
生产环境配置。群组、审批链和通知名单与当前生产流程保持一致。
"""

import os
from dotenv import load_dotenv

load_dotenv()  # 从同目录下的 .env 文件加载环境变量（.env 不会被提交到 git）

# ========== Telegram API 凭证 ==========
# 不要把真实的 api_id / api_hash 写死在这个文件里（这个文件会被提交到 git）。
# 真实值放在同目录的 .env 文件中（参考 .env.example），本文件只负责读取。
API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
SESSION_NAME = "ssc_offer_bot"   # session 文件名，首次登录后会在本地生成 .session 文件

if not API_ID or not API_HASH:
    raise RuntimeError(
        "未找到 TG_API_ID / TG_API_HASH，请复制 .env.example 为 .env 并填入真实值"
    )

# ========== SSC发送审批 ==========
# 所有环境统一使用当前登录账号的收藏夹：Offer用1，转正用2，周年用3。

# ========== 群组 ==========
# 强烈建议使用数字ID而不是群名字符串（更稳定，不受改群名影响）。
# 获取方式：先用 list_chats.py 跑一遍，把打印出来的 ID 复制过来替换下面的值。
GROUP_HRBP = -1003559652510         # 场景一：来源群，HRBP在这里@你发offer消息
GROUP_LEADERSHIP = -1003865890708   # 场景二/三：审批流转 + 最终入职确认发布的群
GROUP_RECRUIT = -1004380831613      # 场景二：简历 & 最终"请招聘私聊我"消息所在群
GROUP_REGULARIZATION_TRIGGER = int(os.environ.get(
    "GROUP_REGULARIZATION_TRIGGER", "-1004492520637"
))
GROUP_ANNIVERSARY_TRIGGER = GROUP_REGULARIZATION_TRIGGER

# ========== 审批链角色（填 Telegram 用户名，不带 @） ==========
LEADER_FIRST = "DaBai10010"        # 一级审批：白一舟，收到"好的"作为一级通过标志
LEADER_SECOND_TECH = "hk88mc996"   # 技术中心专属二级审批人
LEADER_FINAL = "chuqianyiding"     # 终审人（所有部门最终都要走到这一步）

# 判断"编制组织"是否属于技术中心（需要走二级审批）的关键词
TECH_CENTER_KEYWORDS = ["技术中心"]

# ========== 场景三：不同部门 -> 最终"入职信息确认"要@的领导名单 ==========
# 匹配规则：先看 org_unit 是否等于/包含 rule["org_unit"]，
# 再看 rec["入职部门"] (或编制组织) 文本里是否包含 dept_keywords 中的任意一个关键词。
# 命中第一条规则就用它的 leaders 名单。
# 请根据你们实际的部门架构继续增补条目。
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
    # TODO: 继续补充其他中心/部门的规则
]

# 如果一个候选人的部门没有匹配到上面任何规则，用这个兜底名单，
# 并会在日志里打印警告，提醒你去补充配置。
DEFAULT_LEADERS = []  # 未配置的中心/部门不使用审批领导作为通知名单

# ========== 每日人事信息数据同步 ==========
DAILY_REPORT_FOLDER_ID = os.environ.get(
    "DAILY_REPORT_FOLDER_ID", "15Jrw7hl6erl2BFDwkqg5gEj_bOLA1dDk"
)
DAILY_REPORT_RECIPIENT = os.environ.get("DAILY_REPORT_RECIPIENT", "oiyr90557")
DAILY_REPORT_TIMEZONE = os.environ.get("DAILY_REPORT_TIMEZONE", "Asia/Shanghai")
DAILY_REPORT_POLL_SECONDS = int(os.environ.get("DAILY_REPORT_POLL_SECONDS", "300"))

# ========== 转正倒数4天提醒 ==========
REGULARIZATION_TRIGGER_BOT_ID = int(os.environ.get(
    "REGULARIZATION_TRIGGER_BOT_ID", "8416618309"
))
REGULARIZATION_TRIGGER_KEYWORD = "转正提醒-恒睿-转正倒数4天"
REGULARIZATION_OUTPUT_FOLDER_ID = os.environ.get(
    "REGULARIZATION_OUTPUT_FOLDER_ID", "17QEQ5Q1Nyfp1asMiXZYt-4vd4UDHVxAg"
)

# ========== 入职周年提醒 ==========
ANNIVERSARY_TRIGGER_BOT_ID = REGULARIZATION_TRIGGER_BOT_ID
ANNIVERSARY_TRIGGER_KEYWORDS = ("入职周年提醒", "恒睿")
ANNIVERSARY_DRIVE_ROOT_ID = os.environ.get(
    "ANNIVERSARY_DRIVE_ROOT_ID", "13JH168_QwFcGaboQUrPF2sGnCjbXaa7E"
)
ANNIVERSARY_DRIVE_PATH = ("海报助手", "输出", "当月入职周年海报")
ANNIVERSARY_GROUP_RULES = [
    {"name": "恒睿公司-ACFAN特战队-全员群", "keywords": ["ACFAN特战队", "ACFAN"], "chat_id": -1003553653887},
    {"name": "恒睿公司-运营一部-全员群", "keywords": ["运营一部", "运营1部"], "chat_id": -1003663263859},
    {"name": "恒睿公司-运营二部-全员群", "keywords": ["运营二部", "运营2部"], "chat_id": -1003950803307},
    {"name": "恒睿-渠道/商务部-全员群", "keywords": ["渠道部", "商务部", "渠道商务部"], "chat_id": -1003872014182},
    {"name": "恒睿-技术/效能部-全员群", "keywords": ["技术部", "效能部", "技术效能部"], "chat_id": -1003946619557},
]

# ========== 本地状态文件 ==========
DB_PATH = "offer_state.json"
DAILY_REPORT_STATE_PATH = DB_PATH + ".daily_reports.json"
REGULARIZATION_STATE_PATH = DB_PATH + ".regularization.json"
ANNIVERSARY_STATE_PATH = DB_PATH + ".anniversary.json"

# ========== 日志文件 ==========
LOG_PATH = "bot.log"
