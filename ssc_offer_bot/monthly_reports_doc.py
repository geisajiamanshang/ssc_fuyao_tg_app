# -*- coding: utf-8 -*-
"""场景十九：SSC在自己的收藏夹发"员工绩效"，把"共享服务中心-SSC工作群"里本账号（扶摇）
当月发的所有日报原文汇总成一份Word(.docx)发回收藏夹，方便下载。

不依赖第三方库：.docx本质是zip里几个XML文件，这里只写需要的最小几个（跟
onboarding_agreement.docx_to_text读.docx的做法一致，服务器不用多装包）。
日报原文一字不改，只做版式：标题、每篇日报前的日期、"## 【今日结果】"这类二级标题加粗。
"""

import io
import re
import zipfile
from xml.sax.saxutils import escape

_WEEKDAYS = "一二三四五六日"
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '</Types>'
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/></Relationships>'
)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{_W_NS}"><w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="微软雅黑" w:cs="Calibri"/>'
    '<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/>'
    '</w:rPr></w:rPrDefault></w:docDefaults></w:styles>'
)


def mask_trigger_keywords(text, keywords):
    """收藏夹里机器人自己发的提示/文件说明也会被触发监听器收到：带了完整触发词就会
    自己触发自己。把每个关键词拆开一个点，保证发出去的内容不含完整的触发词。"""
    for keyword in keywords:
        if keyword:
            text = (text or "").replace(keyword, keyword[:2] + "·" + keyword[2:])
    return text


def _run(text, bold=False, size=None, color=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    text = escape(_INVALID_XML.sub("", text))
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'


def _paragraph(text, bold=False, size=None, color=None, before=0, after=60, page_break_before=False):
    ppr = f'<w:spacing w:before="{before}" w:after="{after}"/>'
    if page_break_before:
        ppr = "<w:pageBreakBefore/>" + ppr
    return f"<w:p><w:pPr>{ppr}</w:pPr>{_run(text, bold, size, color)}</w:p>"


def _report_paragraphs(day, text, first):
    weekday = _WEEKDAYS[day.weekday()]
    out = [_paragraph(f"{day.isoformat()}（周{weekday}）", bold=True, size=30, after=120,
                      page_break_before=not first)]
    previous_blank = True
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            previous_blank = True
            continue
        if re.fullmatch(r"#\s*日报", stripped):
            continue                      # 每篇已经有日期标题，不重复"# 日报"
        heading = re.match(r"^#{2,}\s*(.+)$", stripped)
        if heading:
            out.append(_paragraph(heading.group(1), bold=True, size=26, before=200, after=80))
        elif stripped.startswith("[") and "[TYPE:" in stripped:
            out.append(_paragraph(stripped, size=18, color="808080"))
        else:
            out.append(_paragraph(stripped.lstrip(">").strip() if stripped.startswith(">") else stripped))
        previous_blank = False
    return out


def build_reports_docx(reports, author, period_label, generated_at):
    """reports: [(date, text), ...]（日期升序）；返回.docx文件的bytes。"""
    first_day, last_day = reports[0][0], reports[-1][0]
    body = [
        _paragraph(f"{author} {period_label}日报汇总", bold=True, size=40, after=160),
        _paragraph(
            f"共{len(reports)}篇日报，日期范围{first_day.isoformat()}至{last_day.isoformat()}；"
            f"{generated_at.strftime('%Y-%m-%d %H:%M')}生成，内容取自群里发送的日报原文，未做改写。",
            size=20, color="808080", after=240),
    ]
    for index, (day, text) in enumerate(reports):
        body.extend(_report_paragraphs(day, text, first=index == 0))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>' + "".join(body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
        'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        zf.writestr("word/styles.xml", _STYLES)
        zf.writestr("word/document.xml", document)
    return buffer.getvalue()
