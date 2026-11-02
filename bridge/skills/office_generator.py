import datetime
import html
import textwrap

from .models import SkillResult, SkillDef

METADATA = {
    "name": "office_generator",
    "version": "1.0.0",
    "category": "productivity",
    "description": "Generate office documents (report, proposal, memo, presentation, email) as Markdown/HTML.",
}

_TEMPLATES = {
    "report": {
        "sections": [
            ("Executive Summary", "Concise overview of the report's purpose, key findings, and recommendations."),
            ("Background", "Context and history relevant to the topic."),
            ("Analysis", "Detailed examination of the subject matter."),
            ("Findings", "Key discoveries and data-driven insights."),
            ("Recommendations", "Actionable suggestions based on findings."),
            ("Conclusion", "Summary and closing remarks."),
        ],
    },
    "proposal": {
        "sections": [
            ("Problem Statement", "Clear description of the problem or opportunity."),
            ("Objectives", "Specific, measurable goals the proposal aims to achieve."),
            ("Methodology", "Approach and methods for achieving the objectives."),
            ("Timeline", "Proposed schedule with key milestones."),
            ("Budget Estimate", "Estimated costs broken down by category."),
            ("Expected Outcomes", "Anticipated results and success criteria."),
        ],
    },
    "memo": {
        "sections": [
            ("Header", "TO / FROM / DATE / SUBJECT"),
            ("Purpose", "Why this memo is being written."),
            ("Summary", "Brief overview of the key information."),
            ("Details", "In-depth explanation and supporting data."),
            ("Action Items", "Specific next steps and responsible parties."),
        ],
    },
    "presentation": {
        "sections": [
            ("Title Slide", "Presentation title, subtitle, author, date."),
            ("Agenda", "Outline of topics to be covered."),
            ("Key Points", "Main content slides with speaker notes."),
            ("Visual Suggestions", "Recommended charts, diagrams, or images."),
            ("Summary Slide", "Recap of key takeaways and call to action."),
        ],
    },
    "email": {
        "sections": [
            ("Subject Line", "Clear, actionable email subject."),
            ("Greeting", "Professional salutation."),
            ("Body", "Concise and actionable message content."),
            ("Closing", "Professional sign-off."),
            ("Signature", "Name, title, contact information."),
        ],
    },
}


def execute(
    doc_type: str = "report",
    topic: str = "",
    format: str = "markdown",
    language: str = "zh",
    **kwargs,
) -> SkillResult:
    valid_doc_types = ("report", "proposal", "memo", "presentation", "email")
    if doc_type not in valid_doc_types:
        return SkillResult.fail("Invalid doc_type '" + doc_type + "'. Must be one of: " + str(valid_doc_types))

    if not topic.strip():
        return SkillResult.fail("topic is required")

    valid_formats = ("markdown", "html")
    if format not in valid_formats:
        return SkillResult.fail("Invalid format '" + format + "'. Must be one of: " + str(valid_formats))

    valid_languages = ("zh", "en")
    if language not in valid_languages:
        return SkillResult.fail("Invalid language '" + language + "'. Must be one of: " + str(valid_languages))

    template = _TEMPLATES[doc_type]
    today = datetime.date.today().isoformat()

    if format == "html":
        content = _generate_html(doc_type, topic, template, today, language)
    else:
        content = _generate_markdown(doc_type, topic, template, today, language)

    return SkillResult.ok(
        output=content,
        data={
            "needs_llm": False,
            "doc_type": doc_type,
            "topic": topic,
            "format": format,
            "language": language,
            "sections_count": len(template["sections"]),
        },
    )


def _generate_markdown(doc_type: str, topic: str, template: dict, date: str, language: str) -> str:
    lines = []
    lang_label = "zh" if language == "zh" else "en"

    if doc_type == "memo":
        lines.append("# MEMORANDUM")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append("| TO | [Recipient] |")
        lines.append("| FROM | [Sender] |")
        lines.append("| DATE | " + date + " |")
        lines.append("| SUBJECT | " + topic + " |")
        lines.append("")
    elif doc_type == "email":
        lines.append("Subject: " + topic + " - [Action Required / FYI / Update]")
        lines.append("")
        lines.append("Dear [Recipient],")
        lines.append("")
    elif doc_type == "presentation":
        lines.append("# " + topic)
        lines.append("")
        lines.append("**Presenter:** [Name]")
        lines.append("**Date:** " + date)
        lines.append("")
    else:
        lines.append("# " + topic)
        lines.append("")
        lines.append("**Date:** " + date)
        lines.append("**Author:** [Author Name]")
        lines.append("**Version:** 1.0")
        lines.append("")

    lines.append("---")
    lines.append("")

    for section_title, section_desc in template["sections"]:
        if doc_type == "memo" and section_title == "Header":
            continue
        if doc_type == "email" and section_title in ("Subject Line", "Greeting"):
            continue

        lines.append("## " + section_title)
        lines.append("")
        lines.append(section_desc)
        lines.append("")

        placeholder = _section_placeholder(doc_type, section_title, topic, language)
        if placeholder:
            lines.append(placeholder)
            lines.append("")

    if doc_type == "email":
        lines.append("Best regards,")
        lines.append("")
        lines.append("[Your Name]")
        lines.append("[Your Title]")
        lines.append("[Contact Information]")

    return "\n".join(lines)


def _generate_html(doc_type: str, topic: str, template: dict, date: str, language: str) -> str:
    escaped_topic = html.escape(topic)
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="' + language + '">')
    parts.append("<head>")
    parts.append("<meta charset='UTF-8'>")
    parts.append("<title>" + escaped_topic + "</title>")
    parts.append("<style>")
    parts.append("body { font-family: sans-serif; max-width: 800px; margin: 2em auto; color: #333; }")
    parts.append("h1 { border-bottom: 2px solid #0066cc; padding-bottom: 0.3em; }")
    parts.append("h2 { color: #0066cc; margin-top: 1.5em; }")
    parts.append("table { border-collapse: collapse; width: 100%; }")
    parts.append("th, td { border: 1px solid #ccc; padding: 0.5em; text-align: left; }")
    parts.append("th { background: #f0f0f0; }")
    parts.append(".placeholder { background: #f9f9f9; padding: 1em; border-left: 3px solid #0066cc; margin: 0.5em 0; }")
    parts.append("</style>")
    parts.append("</head>")
    parts.append("<body>")

    if doc_type == "memo":
        parts.append("<h1>MEMORANDUM</h1>")
        parts.append("<table>")
        parts.append("<tr><th>TO</th><td>[Recipient]</td></tr>")
        parts.append("<tr><th>FROM</th><td>[Sender]</td></tr>")
        parts.append("<tr><th>DATE</th><td>" + date + "</td></tr>")
        parts.append("<tr><th>SUBJECT</th><td>" + escaped_topic + "</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<h1>" + escaped_topic + "</h1>")
        parts.append("<p><strong>Date:</strong> " + date + " | <strong>Author:</strong> [Author Name]</p>")

    parts.append("<hr>")

    for section_title, section_desc in template["sections"]:
        if doc_type == "memo" and section_title == "Header":
            continue
        parts.append("<h2>" + html.escape(section_title) + "</h2>")
        parts.append("<p>" + html.escape(section_desc) + "</p>")
        placeholder = _section_placeholder(doc_type, section_title, topic, language)
        if placeholder:
            parts.append('<div class="placeholder">' + html.escape(placeholder) + "</div>")

    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)


def _section_placeholder(doc_type: str, section_title: str, topic: str, language: str) -> str:
    placeholders = {
        "report": {
            "Executive Summary": "[Write a 2-3 paragraph summary covering the purpose, key findings, and top recommendations regarding: " + topic + "]",
            "Background": "[Provide historical context and relevant background for: " + topic + "]",
            "Analysis": "[Present detailed analysis with supporting data for: " + topic + "]",
            "Findings": "[List numbered findings with evidence for: " + topic + "]",
            "Recommendations": "[Provide prioritized, actionable recommendations based on findings about: " + topic + "]",
            "Conclusion": "[Summarize key points and next steps for: " + topic + "]",
        },
        "proposal": {
            "Problem Statement": "[Describe the specific problem or opportunity that: " + topic + " addresses]",
            "Objectives": "[List 3-5 SMART objectives for: " + topic + "]",
            "Methodology": "[Outline the approach, tools, and methods for: " + topic + "]",
            "Timeline": "[Provide a phased timeline with milestones for: " + topic + "]",
            "Budget Estimate": "[Break down estimated costs by category for: " + topic + "]",
            "Expected Outcomes": "[Define measurable success criteria and expected results for: " + topic + "]",
        },
        "memo": {
            "Purpose": "[State why this memo is being written regarding: " + topic + "]",
            "Summary": "[Provide a brief overview of the key information about: " + topic + "]",
            "Details": "[Give in-depth explanation and supporting data for: " + topic + "]",
            "Action Items": "[List specific next steps with responsible parties and deadlines for: " + topic + "]",
        },
        "presentation": {
            "Title Slide": "[Title: " + topic + " | Subtitle: [Add subtitle] | Presenter: [Name] | Date: [Today]]",
            "Agenda": "[List 4-6 agenda items for the presentation on: " + topic + "]",
            "Key Points": "[For each key point about " + topic + ": Provide heading, 3-5 bullet points, and speaker notes]",
            "Visual Suggestions": "[Recommend specific charts, diagrams, or images for each section about: " + topic + "]",
            "Summary Slide": "[Recap top 3 takeaways and call to action for: " + topic + "]",
        },
        "email": {
            "Body": "[Write concise, actionable message body about: " + topic + " | Include: context, request/action, deadline]",
            "Closing": "[Professional sign-off appropriate for the message about: " + topic + "]",
            "Signature": "[Name | Title | Phone | Email]",
        },
    }
    return placeholders.get(doc_type, {}).get(section_title, "")


def register(registry) -> None:
    registry.register(SkillDef(
        name="office_generator",
        description="[DEPRECATED] Use business.office_generator instead. Legacy document template generator.",
        category="productivity",
        parameters={
            "type": "object",
            "properties": {
                "doc_type": {
                    "type": "string",
                    "enum": ["report", "proposal", "memo", "presentation", "email"],
                    "description": "Type of document to generate",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic or subject of the document",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "html"],
                    "description": "Output format: markdown or html",
                },
                "language": {
                    "type": "string",
                    "enum": ["zh", "en"],
                    "description": "Language of the document: zh (Chinese) or en (English)",
                },
            },
            "required": ["doc_type", "topic"],
        },
        handler=execute,
        timeout=60,
        deprecated=True,
        deprecation_message="Superseded by business.office_generator (real PPT/Word/Excel/PDF generation via python-pptx/docx/openpyxl/reportlab).",
    ))
