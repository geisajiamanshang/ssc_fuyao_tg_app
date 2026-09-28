# -*- coding: utf-8 -*-
"""
"员工自评"自动填表：SSC在收藏夹发"员工自评"触发后，从"共享服务中心-SSC工作
群"收集本账号当月发送的日报（[TYPE:日报]标签），交给GPT生成"本期总结"四项
和"Agent效能自评"的AI工具使用说明，再用浏览器自动化登录人效通OneHR
（m-reportsys.cc）把内容填进 /self-eval 表单草稿。表单本身会自动保存草稿，
机器人只负责填，不点"正式提交"，交由SSC本人核实后自己提交。

日报格式（"共享服务中心-SSC工作群"里本账号自己发的消息）示例：

    # 日报

    [REPORT-ORG:综合行政] [LEVEL:L3] [TYPE:日报] [DATE:2026-09-24]

    > 提交人: 扶摇
    > 岗位: SSC主管
    > 层级: L3

    ## 【今日结果】
    ...
    ## 【死锁阻碍】
    ...
    ## 【专项复盘】
    ...
    ## 【明日动作】
    ...

【入职信息同步】类消息不带这个格式，靠 [TYPE:日报] 标签精确识别，不是简单
按"日报"两个字模糊匹配，避免误把其他提到"日报"字样的消息也算进来。
"""

import json
import re
from datetime import date

import requests

_TYPE_TAG_RE = re.compile(r"\[TYPE:\s*日报\s*\]")
_DATE_TAG_RE = re.compile(r"\[DATE:\s*(\d{4})-(\d{2})-(\d{2})\s*\]")

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

# 人效通OneHR"员工自评"表单里，本期总结/Agent效能自评相关字段各自的字数
# 上限，跟表单页面上"0/500""0/200""0/300"这些提示一一对应。
REQUIRED_FIELDS = ("work_summary", "highlight", "challenge", "next_focus", "agent_usage")
FIELD_MAX_LENGTHS = {
    "work_summary": 500,
    "highlight": 200,
    "challenge": 200,
    "next_focus": 200,
    "agent_usage": 300,
}

# Agent效能自评的三维评分固定填80——日报里通常没有量化"用AI提效"的具体数据，
# 与其让GPT瞎猜0-100的分数，不如固定一个值，只让GPT写文字说明（agent_usage）。
AGENT_SCORE_FIXED_VALUE = 80


def is_daily_report(text):
    """按 [TYPE:日报] 标签判断是否是日报消息，不是就返回 False。"""
    return bool(_TYPE_TAG_RE.search(text or ""))


def report_date(text):
    """从 [DATE:YYYY-MM-DD] 标签取日报所属日期；标签缺失或日期不合法时返回 None。"""
    match = _DATE_TAG_RE.search(text or "")
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def collect_month_reports(messages, year, month):
    """从消息列表（每个对象需有 .raw_text 和 .date 属性，兼容Telethon消息
    对象）中筛出属于指定年月的日报，按日期升序返回 [(date, text), ...]。

    优先用消息文本里的 [DATE:...] 标签判断所属月份；标签缺失或解析失败时，
    退回该消息在Telegram里的实际发送时间。
    """
    collected = []
    for message in messages:
        text = getattr(message, "raw_text", "") or ""
        if not is_daily_report(text):
            continue
        day = report_date(text)
        if day is None:
            sent = getattr(message, "date", None)
            day = sent.date() if sent else None
        if day is None or day.year != year or day.month != month:
            continue
        collected.append((day, text.strip()))
    collected.sort(key=lambda item: item[0])
    return collected


def build_self_eval_prompt(reports, period_label):
    """把本月日报原文拼进GPT的提示词，要求按人效通OneHR"员工自评"表单的
    字段要求（工作说明/本期亮点/本期挑战/下期重点均为必填，且工作说明要
    量化目标达成情况）输出JSON，外加Agent效能自评的AI工具使用说明。
    """
    reports_text = "\n\n".join(
        f"【{day.isoformat()} 日报】\n{text}" for day, text in reports
    ) or "（本月未找到任何日报，如实说明工作记录暂缺，不要编造内容）"
    return (
        "你是共享服务中心SSC主管的工作助理，需要基于下面这段时间"
        "（" + period_label + "）本人在工作群发送的每日工作日报，撰写"
        "\"人效通OneHR\"系统里\"员工自评\"表单的内容。只依据日报里出现的真实"
        "信息撰写，不要编造具体数字或事件；日报没有给出量化数据时，用日报"
        "里\"关键数据打卡\"部分列出的内容做概括，不要凭空编造百分比或达成率。\n\n"
        "每个字段都要写到接近字数上限（下限和上限相差不超过100字），不能"
        "写完关键数字就草草结束。素材不够撑满篇幅时，用工作方法、处理"
        "流程、跨部门协同、遇到问题时怎么排查解决等日报里确实提到但还没"
        "展开的真实细节去充实内容，把简单的一句话拆开讲清楚前因后果——"
        "但不要为了凑字数编造新的数字、事件或没发生过的细节。\n\n"
        "请只输出一个JSON对象，不要有任何其他文字、不要用代码块包裹，"
        "包含以下五个字段：\n"
        '{\n'
        '  "work_summary": "工作说明，不少于400字、不超过500字，需体现当月'
        '主要工作内容和关键数据（入职/离职/转正/异动人数等日报中出现的'
        '具体数字），并展开说明具体的工作方法和处理过程",\n'
        '  "highlight": "本期亮点，不少于100字、不超过200字，展开说明这个'
        '亮点具体是怎么做到的",\n'
        '  "challenge": "本期挑战，不少于100字、不超过200字，展开说明挑战'
        '的具体表现和应对过程",\n'
        '  "next_focus": "下期重点，不少于100字、不超过200字，展开说明'
        '具体的行动计划",\n'
        '  "agent_usage": "AI工具使用说明，不少于200字、不超过300字，基于'
        '日报中与AI/效能相关的内容（如模块标签[AI工具建设]、提到学习或'
        '使用AI的描述）展开说明本月使用AI工具的实际情况、学到了什么、'
        '打算怎么应用；如果日报完全没有提到，如实说明本月暂无AI工具使用'
        '记录，不要编造"\n'
        '}\n\n'
        "以下是这段时间的日报原文：\n\n" + reports_text
    )


def call_openai_chat(api_key, model, prompt, timeout=60):
    """调用OpenAI Chat Completions接口，返回模型输出的原始文本内容。"""
    response = requests.post(
        OPENAI_CHAT_COMPLETIONS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


def parse_self_eval_response(raw_content):
    """解析GPT返回的JSON文本，校验五个字段都齐全，并按各自的表单字数上限
    截断——不依赖GPT一定守规矩，机器人自己兜底，避免填表时超出maxlength。
    """
    content = (raw_content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"```\s*$", "", content).strip()
    data = json.loads(content)
    result = {}
    for field in REQUIRED_FIELDS:
        value = (data.get(field) or "").strip()
        if not value:
            raise ValueError(f"GPT返回内容缺少字段：{field}")
        result[field] = value[:FIELD_MAX_LENGTHS[field]]
    return result


def format_self_eval_preview(content, period_label):
    """拼一段给SSC看的预览文字，随通知一起发到收藏夹，方便SSC不用打开
    网页也能先看一眼GPT写了什么内容，再决定要不要去网站上核对提交。
    """
    return (
        f"【员工自评草稿预览 · {period_label}】\n\n"
        f"工作说明：\n{content['work_summary']}\n\n"
        f"本期亮点：\n{content['highlight']}\n\n"
        f"本期挑战：\n{content['challenge']}\n\n"
        f"下期重点：\n{content['next_focus']}\n\n"
        f"AI工具使用说明：\n{content['agent_usage']}\n\n"
        f"Agent效能自评三维评分已固定填{AGENT_SCORE_FIXED_VALUE}分。"
    )


# 表单字段的CSS选择器：2026-09-28 在真实 /self-eval 页面的浏览器控制台里
# 用 document.querySelectorAll 核对过，这几个id是准确的。
SELF_EVAL_FIELD_SELECTORS = {
    "work_summary": "#note",
    "highlight": "#highlight",
    "challenge": "#challenge",
    "next_focus": "#next_focus",
    "agent_usage": "#agent-usage",
}
SELF_EVAL_SCORE_SELECTORS = ("#sa1", "#sa2", "#sa3")


async def fill_self_eval_form(base_url, login_code, login_password, content):
    """登录人效通OneHR，把content（parse_self_eval_response的返回值）填进
    /self-eval 表单的"本期总结"和"Agent效能自评"对应输入框。表单本身会自动
    保存草稿（页面右上角"草稿已保存"），这里全程不点"正式提交"，最终提交
    交给SSC本人登录网站核实后手动完成。

    注意：登录页（员工编码/密码输入框、登录按钮）的选择器是按登录页上的
    可见文字猜的，还没有像表单字段那样在真实页面核对过——第一次在测试
    环境跑这个功能时，如果登录这一步失败，很可能是这里的选择器需要按
    真实页面调整。
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(f"{base_url}/login")
            await page.get_by_label("员工编码").fill(login_code)
            await page.get_by_label("密码").fill(login_password)
            await page.get_by_role("button", name="登录").click()
            await page.wait_for_url(re.compile(r"/self-eval"), timeout=30000)

            for field, selector in SELF_EVAL_FIELD_SELECTORS.items():
                await page.fill(selector, content[field])
            for selector in SELF_EVAL_SCORE_SELECTORS:
                await page.fill(selector, str(AGENT_SCORE_FIXED_VALUE))

            # 触发失焦，让页面自身的自动保存草稿逻辑生效；全程不点"正式提交"。
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(2000)
        finally:
            await browser.close()
