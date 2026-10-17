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
    {
        "org_unit": "运营中心",
        "dept_keywords": ["AIGC原创部"],
        "leaders": ["DaBai10010", "chuqianyiding", "wean4790"],
    },
]
DEFAULT_LEADERS = []

DAILY_REPORT_FOLDER_ID = os.environ.get(
    "DAILY_REPORT_FOLDER_ID", "15Jrw7hl6erl2BFDwkqg5gEj_bOLA1dDk"
)
DAILY_REPORT_RECIPIENT = os.environ.get("DAILY_REPORT_RECIPIENT", "oiyr90557")
DAILY_REPORT_TIMEZONE = os.environ.get("DAILY_REPORT_TIMEZONE", "Asia/Shanghai")
DAILY_REPORT_POLL_SECONDS = int(os.environ.get("DAILY_REPORT_POLL_SECONDS", "300"))

# 星辰小组工作对接群里的"星辰小助手"机器人。数字ID不依赖记忆，启动时按用户名
# 自动解析（见 main.resolve_trigger_bot_id）；如需固定，可在 .env 里直接填
# REGULARIZATION_TRIGGER_BOT_ID 覆盖。解析失败时保持0，即忽略所有群内消息，
# 不会误放行别的发送者。
REGULARIZATION_TRIGGER_BOT_USERNAME = os.environ.get(
    "REGULARIZATION_TRIGGER_BOT_USERNAME", "checker_xing_bot"
)
REGULARIZATION_TRIGGER_BOT_ID = int(
    os.environ.get("REGULARIZATION_TRIGGER_BOT_ID", "0")
)
REGULARIZATION_TRIGGER_KEYWORD = "转正提醒-恒睿-转正倒数4天"
REGULARIZATION_TODAY_TRIGGER_KEYWORD = "转正提醒-恒睿-今日转正"
# 转正助手/输出：每个月的转正文件夹（转正信息、转正海报）都在这个文件夹里面，要分享给
# 机器人的Google服务账号。服务器 .env.prod 里如果设置了 REGULARIZATION_OUTPUT_FOLDER_ID，
# 会覆盖这里的默认值，换文件夹时记得一起改。
# https://drive.google.com/drive/u/1/folders/1ow3D3vRgUSQ6PctbcoAmbdNkjzh3kF83
REGULARIZATION_OUTPUT_FOLDER_ID = os.environ.get(
    "REGULARIZATION_OUTPUT_FOLDER_ID", "1ow3D3vRgUSQ6PctbcoAmbdNkjzh3kF83"
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
# 转正提醒来源群（星辰小组工作对接群，GROUP_REGULARIZATION_TRIGGER）里，只认这个账号
# 发的"全员群"关键词，别人说到这三个字不触发；SSC3组内部沟通群不受这条限制。只在生产环境生效。
ALL_STAFF_NOTICE_TRIGGER_SENDER = os.environ.get(
    "ALL_STAFF_NOTICE_TRIGGER_SENDER", "xingchendahai990"
).strip().lstrip("@")

# 招聘群"私发"回复确认 / 招聘私聊候选人信息确认，原本会随机延迟10-30秒后
# 给对方消息点👌或❤️表情，模拟SSC手动确认收到的节奏；2026-10起按要求
# 暂停这两处自动点表情的动作，草稿生成、候选人信息合并等其余处理不受
# 影响。需要恢复时把下面两个值分别改回 True 即可。
RECRUIT_GROUP_SENT_REACTION_ENABLED = False
RECRUIT_PRIVATE_DM_REACTION_ENABLED = False

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

# ========== 当日人事信息数据同步 ==========
# "人事数据同步-SSC3组"里【入职信息同步】【转正信息同步】不带"编制组织"字段，
# 只带"部门-小组"，要靠部门关键词倒推所属中心；【离职信息同步】【人员异动信息同步】
# 已经直接带"编制组织"字段，不查这张表。顺序即汇总消息里各中心出现的顺序。
DAILY_SYNC_CENTER_ORDER = ["运营中心", "技术中心", "渠道中心", "商务中心", "效能中心"]
DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS = {
    "运营中心": ["运营1部", "运营一部", "运营2部", "运营二部", "运营3部", "运营三部", "ACFAN"],
    "技术中心": ["研发部"],
    "渠道中心": ["渠道部"],
    "商务中心": ["传统销售部"],
    "效能中心": ["效能部"],
}
DAILY_SYNC_COMPANY_LABEL = "恒睿"

# ========== 员工自评自动填表 ==========
# 触发关键词：SSC在自己的收藏夹发这句话（包含即可，不要求整条消息完全一样）。
SELF_EVAL_TRIGGER_KEYWORD = "员工自评"
# 调用OpenAI把当月日报总结成"本期总结"+"Agent效能自评"文案。
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# 人效通OneHR（m-reportsys.cc）登录信息；用浏览器自动化登录后把内容填进
# /self-eval 表单草稿，不点"正式提交"，交由SSC本人核实后自己提交。
ONEHR_BASE_URL = os.environ.get("ONEHR_BASE_URL", "https://m-reportsys.cc").rstrip("/")
ONEHR_LOGIN_CODE = os.environ.get("ONEHR_LOGIN_CODE", "").strip()
ONEHR_LOGIN_PASSWORD = os.environ.get("ONEHR_LOGIN_PASSWORD", "").strip()

# ========== 帐号申请自动化 ==========
# SSC收藏夹出现"帐号申请"关键词后，读取"花名册"和"花名册（机器人）"两张
# 在线Google表格（真实地址记在花名册Drive文件夹里的"共享资源地址.rtf"，
# 不是文件夹本身直接放着这两张表，所以这里直接记录解析出来的表格ID/分页
# gid，不依赖每次现读那份说明文件），筛出生效日期>=ACCOUNT_APPLICATION_
# CUTOVER_DATE（不论部门，早于这个日期的历史存量不处理）且距今>=
# ACCOUNT_APPLICATION_MIN_DAYS_SINCE_EFFECTIVE天、且工作TG(AD列)还没换成
# 真正工作TG的人——具体表现为AD列空白、填的是"同上"这类占位文字、或者跟
# AE列(私人联系方式)完全相同；同名以"花名册"为准，重复名单静默按"花名册"
# 处理，不再发收藏夹提示。
# 按O列部门套理由：研发部/效能部固定"新人入职工作需要"，套用【员工账号
# 申请】格式；其他部门"新人入职满7天"，套用
# 【员工工作帐号申请】格式——两种格式都是照抄"帐号申请助手/模版.rtf"里
# 对应部门的真实历史例子，见account_application.py。生成的草稿分别发到
# 收藏夹；SSC统一发送111放行，逐条间隔随机5-10秒转发到工作帐号需求群-
# SSC3组（复用现有的GROUP_ACCOUNT_REQUEST_WORK），每条发送成功后立即
# 删除对应收藏夹草稿。
#
# 读取这两张表需要Sheets API v4（按gid精确定位分页，Drive的CSV导出接口
# 不支持选分页），除了服务账号已有的drive.readonly，还需要额外申请
# spreadsheets.readonly这个权限范围，并在服务账号所在的Google Cloud项目
# 里启用"Google Sheets API"（一次性设置，去Cloud Console的"API和服务→库"
# 搜索启用）；这两张表本身也需要单独分享给服务账号邮箱（跟分享Drive文件夹
# 是两回事）。
ACCOUNT_APPLICATION_TRIGGER_KEYWORD = "帐号申请"
# 花名册：https://docs.google.com/spreadsheets/d/1DgnePrJOwA0sa8v4wJbv3RjFmdXvhGVN9f1TrTuzJng/edit?gid=139264850
ACCOUNT_APPLICATION_ROSTER_SPREADSHEET_ID = os.environ.get(
    "ACCOUNT_APPLICATION_ROSTER_SPREADSHEET_ID",
    "1DgnePrJOwA0sa8v4wJbv3RjFmdXvhGVN9f1TrTuzJng",
)
ACCOUNT_APPLICATION_ROSTER_SHEET_GID = int(os.environ.get(
    "ACCOUNT_APPLICATION_ROSTER_SHEET_GID", "139264850"
))
# 花名册（机器人）：https://docs.google.com/spreadsheets/d/1OoNt1C0YyO4pBjle7eQjbuuepOpKk1gK8JlumdagGWM/edit?gid=139264850
ACCOUNT_APPLICATION_ROSTER_BOT_SPREADSHEET_ID = os.environ.get(
    "ACCOUNT_APPLICATION_ROSTER_BOT_SPREADSHEET_ID",
    "1OoNt1C0YyO4pBjle7eQjbuuepOpKk1gK8JlumdagGWM",
)
ACCOUNT_APPLICATION_ROSTER_BOT_SHEET_GID = int(os.environ.get(
    "ACCOUNT_APPLICATION_ROSTER_BOT_SHEET_GID", "139264850"
))
# 研发部/效能部理由固定"新人入职工作需要"；其他部门理由"新人入职满7天"。
ACCOUNT_APPLICATION_TECH_DEPARTMENTS = ("研发部", "效能部")
# 不论部门，只对生效日期>=这个日期起的人生效；历史存量（哪怕是研发部/
# 效能部）不在本次自动化范围内，需要的话人工处理。
ACCOUNT_APPLICATION_CUTOVER_DATE = "2026-10-01"
# 生效日期还必须距今>=这么多天才处理——刚生效没几天，工作TG可能还没来得及
# 配置，先不打扰。
ACCOUNT_APPLICATION_MIN_DAYS_SINCE_EFFECTIVE = 6

# 联合管理群出现【入职信息确认】后，把"候选人编码"写进花名册（机器人）表
# D列（按"候选人姓名"在C列找已有行，只填这一格）。表格：
# https://docs.google.com/spreadsheets/d/1cCAsC1qHTSJ32uDJlDFKTQ4mPkNbwV-x
# 服务账号需要对这张表有"编辑者"权限，且启用了 Google Sheets API。
ROSTER_CODE_SPREADSHEET_ID = os.environ.get(
    "ROSTER_CODE_SPREADSHEET_ID", "1cCAsC1qHTSJ32uDJlDFKTQ4mPkNbwV-x"
)
ROSTER_CODE_SHEET_GID = int(os.environ.get("ROSTER_CODE_SHEET_GID", "1173062379"))
ROSTER_CODE_NAME_COLUMN = "C"
ROSTER_CODE_CODE_COLUMN = "D"

# SSC在自己的收藏夹发带"培训"关键词的消息，触发按花名册（机器人）AR列
# 日期筛出"明天"要培训的人，生成【次日培训信息同步】草稿发到收藏夹，经
# 审批码14（测试14）放行到共享服务中心-远程培训沟通群。跟ROSTER_CODE用的
# 是同一张"花名册（机器人）"表格（表头只占1行，数据从第2行开始），列位置
# SSC本人核对过：简历名=E，编制组织=M，部门=P，岗位=U，培训日期=AR；
# "服务单位"这张表没有单独列，固定写"恒睿"，复用DAILY_SYNC_COMPANY_LABEL；
# 分组顺序复用DAILY_SYNC_CENTER_ORDER。
# https://docs.google.com/spreadsheets/d/1NuEckgwIEjzegpktBx4O6UxjFXl32LruM1j9JsYVOGw/edit?gid=1173062379
TRAINING_SYNC_TRIGGER_KEYWORD = "培训"
TRAINING_SYNC_ROSTER_SPREADSHEET_ID = os.environ.get(
    "TRAINING_SYNC_ROSTER_SPREADSHEET_ID",
    "1NuEckgwIEjzegpktBx4O6UxjFXl32LruM1j9JsYVOGw",
)
TRAINING_SYNC_ROSTER_SHEET_GID = int(os.environ.get(
    "TRAINING_SYNC_ROSTER_SHEET_GID", "1173062379"
))

# 场景十四：SSC收藏夹出现"入职协议"关键词后，到入职协议文件夹下找当月文件夹
# （例：2026年-10月），取里面当日入职的所有入职协议（文件名 花名_入职协议_日期），
# 从协议内容里读出私人TG，把协议的Drive链接私发给他；每人一条草稿进收藏夹，
# 审批码15统一放行。
ONBOARDING_AGREEMENT_TRIGGER_KEYWORD = "入职协议"
# https://drive.google.com/drive/u/1/folders/1tmNkfhM35ZbYYXu1UncC7dZCsbx_BUJq
# 这个文件夹要分享给机器人的Google服务账号，否则机器人看不到里面的文件。
ONBOARDING_AGREEMENT_FOLDER_ID = os.environ.get(
    "ONBOARDING_AGREEMENT_FOLDER_ID", "1tmNkfhM35ZbYYXu1UncC7dZCsbx_BUJq"
)

# 收藏夹发审批码151：把当日所有入职协议的链接汇总成一条消息，私发给萌萌姐审批。
ONBOARDING_AGREEMENT_LEADER_TG = os.environ.get("ONBOARDING_AGREEMENT_LEADER_TG", "@woshidaimeng87")

# 场景十五：SSC收藏夹出现"钱包提醒"关键词后，比对花名册（机器人）（同培训同步那张
# 表）里今日入职（AR列）的人和钱包表单里"首次提交（新人入职）"的条目，没填写的人
# 向工作TG（花名册AE列）发提醒；草稿先进收藏夹，审批码17放行。两张表都要分享给
# 机器人的Google服务账号。
WALLET_REMINDER_TRIGGER_KEYWORD = "钱包提醒"

# 场景十六：SSC收藏夹出现"培训通知"关键词后，给花名册（机器人）G列入职日期是今天的人，
# 向私人TG（AF列）私发学习群链接；草稿先进收藏夹，审批码18放行。注意：这个词里含"培训"，
# 场景十三的触发词也是"培训"，所以场景十三遇到"培训通知"会主动让开，本场景的所有提示
# 文案也不能出现"培训"两个字，否则会反过来触发场景十三。
TRAINING_NOTICE_TRIGGER_KEYWORD = "培训通知"

# 场景十七：SSC在自己的收藏夹发"拉人"（整条消息就是这两个字），读花名册，把M列（编制组织）
# 是"技术中心"的人的工作TG（AE列）都拉进下面这个群，并把名单列出来。花名册：
# https://docs.google.com/spreadsheets/d/1DgnePrJOwA0sa8v4wJbv3RjFmdXvhGVN9f1TrTuzJng/edit?gid=139264850
# 群ID是普通群（basic group）的ID，写成负数（Telethon认-5517058150为普通群，不是超级群）。
PULL_GROUP_TRIGGER = "拉人"
PULL_GROUP_SPREADSHEET_ID = os.environ.get(
    "PULL_GROUP_SPREADSHEET_ID", "1DgnePrJOwA0sa8v4wJbv3RjFmdXvhGVN9f1TrTuzJng"
)
PULL_GROUP_SHEET_GID = int(os.environ.get("PULL_GROUP_SHEET_GID", "139264850"))
PULL_GROUP_CHAT_ID = int(os.environ.get("PULL_GROUP_CHAT_ID", "-5517058150"))
PULL_GROUP_CENTER = os.environ.get("PULL_GROUP_CENTER", "技术中心")
WALLET_REMINDER_FORM_SPREADSHEET_ID = os.environ.get(
    "WALLET_REMINDER_FORM_SPREADSHEET_ID", "1SrvH7LuKqlekXzUUxbMAY3VNT54ApXNqG6bki9bnhXQ"
)
WALLET_REMINDER_FORM_SHEET_GID = int(os.environ.get("WALLET_REMINDER_FORM_SHEET_GID", "639628649"))

# 测试环境启动时会检查所有可发送目标不属于这些生产群。
PRODUCTION_CHAT_IDS = frozenset({
    -1003559652510,  # HRBP沟通群
    -1003865890708,  # 联合管理群
    -1004380831613,  # 招聘群
    -1004472320269,  # 星辰小组工作对接群（触发群）
    -1003553653887,  # ACFAN全员群
    -1003663263859,  # 运营一部全员群
    -1003950803307,  # 运营二部全员群
    -1003872014182,  # 渠道/商务部全员群
    -1003946619557,  # 技术/效能部全员群
    -1004334431069,  # 工作帐号需求群-SSC3组
    -5164874973,  # 北斗离职人员-同步商务中心群
    -1003855659853,  # 共享服务中心-远程培训沟通群
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
