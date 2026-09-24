# -*- coding: utf-8 -*-
"""
生产环境配置。群组、审批链和通知名单与当前生产流程保持一致。
"""

import os

from config_common import *

SESSION_NAME = os.environ.get("TG_SESSION_NAME", "ssc_offer_bot_prod")

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
GROUP_REGULARIZATION_SYNC = int(os.environ.get(
    "GROUP_REGULARIZATION_SYNC", "-1004468512291"
))  # 人事信息同步-SSC3组
# 预入职登记群：入职确认发布到联合管理群后再经收藏夹审批(11)转发到这里。
GROUP_PRE_ONBOARDING = int(os.environ.get(
    "GROUP_PRE_ONBOARDING", "-1004351797001"
)) or None
# 新人培训群：等待补充真实群号前先留空（不影响其他功能，功能自动禁用直到配置）
GROUP_TRAINING = int(os.environ.get("GROUP_TRAINING", "0")) or None
# SSC3组内部工作沟通群：与GROUP_REGULARIZATION_TRIGGER共同监控"全员群"关键词。
GROUP_SSC3_INTERNAL_CHAT = int(os.environ.get(
    "GROUP_SSC3_INTERNAL_CHAT", "-1003801083059"
)) or None

# ========== 审批链角色（填 Telegram 用户名，不带 @） ==========
LEADER_FIRST = "DaBai10010"        # 一级审批：白一舟，收到"好的"作为一级通过标志
LEADER_SECOND_TECH = "hk88mc996"   # 技术中心专属二级审批人
LEADER_FINAL = "chuqianyiding"     # 终审人（所有部门最终都要走到这一步）

ANNIVERSARY_GROUP_RULES = [
    {"name": "恒睿公司-ACFAN特战队-全员群", "keywords": ["ACFAN特战队", "ACFAN", "AIGC原创部", "AIGC"], "chat_id": -1003553653887},
    {"name": "恒睿公司-运营一部-全员群", "keywords": ["运营一部", "运营1部"], "chat_id": -1003663263859},
    {"name": "恒睿公司-运营二部-全员群", "keywords": ["运营二部", "运营2部"], "chat_id": -1003950803307},
    {"name": "恒睿-渠道/商务部-全员群", "keywords": ["渠道部", "商务部", "渠道商务部"], "chat_id": -1003872014182},
    {"name": "恒睿-技术/效能部-全员群", "keywords": ["技术部", "效能部", "技术效能部", "技术中心", "研发部"], "chat_id": -1003946619557},
]

# 账号申请转发目标群：外事群ID待补充，留空时账号申请（工作类目除外）功能自动跳过。
GROUP_ACCOUNT_REQUEST_FOREIGN = int(os.environ.get("GROUP_ACCOUNT_REQUEST_FOREIGN", "0")) or None
# 工作帐号需求群-SSC3组：账号申请(工作类目)和离职审批(84 员工帐号回收)共用同一个群。
GROUP_ACCOUNT_REQUEST_WORK = int(os.environ.get(
    "GROUP_ACCOUNT_REQUEST_WORK", "-1004334431069"
)) or None
# 北斗离职人员-同步商务中心群：离职审批(83 离职信息同步)转发目标之一。
GROUP_OFFBOARDING_BUSINESS_SYNC = int(os.environ.get(
    "GROUP_OFFBOARDING_BUSINESS_SYNC", "-5164874973"
)) or None

# ========== 本地状态文件 ==========
DB_PATH = "offer_state.json"
DAILY_REPORT_STATE_PATH = DB_PATH + ".daily_reports.json"
REGULARIZATION_STATE_PATH = DB_PATH + ".regularization.json"
ANNIVERSARY_STATE_PATH = DB_PATH + ".anniversary.json"
ONBOARDING_TRAINING_STATE_PATH = DB_PATH + ".onboarding_training.json"
ALL_STAFF_NOTICE_STATE_PATH = DB_PATH + ".all_staff_notice.json"
ACCOUNT_REQUEST_STATE_PATH = DB_PATH + ".account_request.json"
OFFBOARDING_STATE_PATH = DB_PATH + ".offboarding.json"

# ========== 日志文件 ==========
LOG_PATH = "bot.log"
