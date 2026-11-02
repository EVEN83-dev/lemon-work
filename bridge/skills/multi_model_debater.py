import difflib
from collections import Counter

from .models import SkillResult, SkillDef

METADATA = {
    "name": "multi_model_debater",
    "version": "1.0.0",
    "category": "reasoning",
    "description": "Multi-perspective debate generation with structured format.",
}

_ROLE_DATA = {
    "Proponent": {
        "position": "in favor",
        "key_points": [
            "Strong empirical evidence supports the proposition.",
            "Historical precedent demonstrates consistent positive outcomes.",
            "Cost-benefit analysis favors adoption of the position.",
        ],
        "rebuttals": [
            "The counter-evidence cited is based on a narrow sample that does not generalize.",
            "Resource concerns are overstated; efficiency gains offset initial investment.",
            "Risk assessments often employ overly conservative assumptions.",
        ],
    },
    "Opponent": {
        "position": "against",
        "key_points": [
            "The supporting evidence relies on correlation rather than causation.",
            "Significant unintended consequences remain unaddressed.",
            "Alternative approaches achieve comparable results with fewer risks.",
        ],
        "rebuttals": [
            "The claimed benefits assume ideal conditions that rarely obtain in practice.",
            "Historical precedents cited by proponents differ in crucial contextual factors.",
            "Long-term sustainability data is insufficient to justify commitment.",
        ],
    },
    "Neutral Analyst": {
        "position": "neutral observation",
        "key_points": [
            "Both sides present partially valid arguments that are not mutually exclusive.",
            "The quality of evidence varies significantly across different sub-claims.",
            "Contextual factors may determine which side's arguments apply more strongly.",
        ],
        "rebuttals": [
            "Absolute positions on either side oversimplify a nuanced reality.",
            "The debate would benefit from narrower, more precisely scoped claims.",
            "Empirical testing of specific predictions could resolve key disagreements.",
        ],
    },
    "Devil's Advocate": {
        "position": "challenging assumptions",
        "key_points": [
            "The framing of the debate itself may presuppose a false dichotomy.",
            "Unexamined assumptions underlie both the for and against positions.",
            "The strongest version of each side's argument has not yet been presented.",
        ],
        "rebuttals": [
            "Challenging assumptions without offering alternatives produces analysis paralysis.",
            "The meta-critique, while valid, does not excuse failing to take a position.",
            "Constructive engagement requires engaging with arguments as stated, not idealized versions.",
        ],
    },
}


def execute(topic: str, perspectives: int = 3, **kwargs) -> SkillResult:
    perspectives = max(2, min(4, perspectives))

    perspective_roles = {
        2: ["Proponent", "Opponent"],
        3: ["Proponent", "Opponent", "Neutral Analyst"],
        4: ["Proponent", "Opponent", "Neutral Analyst", "Devil's Advocate"],
    }

    roles = perspective_roles.get(perspectives, perspective_roles[3])

    lines = []
    lines.append("=" * 64)
    lines.append("MULTI-PERSPECTIVE DEBATE ANALYSIS")
    lines.append("=" * 64)
    lines.append("")
    lines.append("Topic: " + topic)
    lines.append("Perspectives: " + str(perspectives))
    lines.append("Roles: " + ", ".join(roles))
    lines.append("")

    lines.append("## Opening Statements")
    lines.append("")
    for role in roles:
        rd = _ROLE_DATA[role]
        lines.append("**" + role + "** (" + rd["position"] + "):")
        opening = "Regarding '" + topic + "', the " + role.lower() + " holds that the evidence " + rd["position"] + " merits careful examination. " + rd["key_points"][0]
        lines.append("  " + opening)
        lines.append("")

    lines.append("## Key Arguments")
    lines.append("")
    all_key_texts = []
    for role in roles:
        rd = _ROLE_DATA[role]
        lines.append("**" + role + "**:")
        for j, pt in enumerate(rd["key_points"], 1):
            adapted = pt.replace("the proposition", "'" + topic + "'").replace("the position", "this position on '" + topic + "'")
            lines.append("  " + str(j) + ". " + adapted)
            all_key_texts.append(adapted)
        lines.append("")

    lines.append("## Cross-Examination")
    lines.append("")
    for i, role in enumerate(roles):
        rd = _ROLE_DATA[role]
        next_role = roles[(i + 1) % len(roles)]
        next_rd = _ROLE_DATA[next_role]
        challenge = next_rd["key_points"][0].replace("the proposition", "'" + topic + "'").replace("the position", "this position")
        lines.append(next_role + " challenges " + role + ": " + challenge)
        lines.append("")

    lines.append("## Rebuttals")
    lines.append("")
    for role in roles:
        rd = _ROLE_DATA[role]
        lines.append("**" + role + "**:")
        for j, reb in enumerate(rd["rebuttals"], 1):
            adapted = reb.replace("the proposition", "'" + topic + "'")
            lines.append("  " + str(j) + ". " + adapted)
        lines.append("")

    lines.append("## Final Summary")
    lines.append("")

    all_words = " ".join(all_key_texts).lower().split()
    word_freq = Counter(w for w in all_words if len(w) > 4)
    top_words = word_freq.most_common(5)

    lines.append("Key recurring terms across all perspectives:")
    for word, count in top_words:
        lines.append("  - '" + word + "' (mentioned " + str(count) + " times)")
    lines.append("")

    for i in range(len(roles)):
        for j in range(i + 1, len(roles)):
            text_a = " ".join(_ROLE_DATA[roles[i]]["key_points"])
            text_b = " ".join(_ROLE_DATA[roles[j]]["key_points"])
            ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
            lines.append("Overlap " + roles[i] + " vs " + roles[j] + ": " + str(round(ratio, 3)))
    lines.append("")

    lines.append("Areas of potential agreement:")
    for role in roles:
        if role in ("Neutral Analyst", "Devil's Advocate"):
            lines.append("  - " + role + " identifies common ground in: " + _ROLE_DATA[role]["key_points"][0].replace("the proposition", "'" + topic + "'").replace("The debate", "The debate on '" + topic + "'"))
    lines.append("")
    lines.append("Recommended further inquiry:")
    lines.append("  - Empirical testing of specific claims from each perspective")
    lines.append("  - Narrower scoping of the topic to resolve key disagreements")
    lines.append("  - Examination of contextual factors that may favor different positions")

    report = "\n".join(lines)

    return SkillResult.ok(
        output=report,
        data={
            "needs_llm": False,
            "topic": topic,
            "perspectives": perspectives,
            "roles": roles,
            "top_terms": [(w, c) for w, c in top_words],
        },
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="multi_model_debater",
        description="Multi-perspective debate with structured format (2-4 perspectives).",
        category="reasoning",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Debate topic",
                },
                "perspectives": {
                    "type": "integer",
                    "description": "Number of debate perspectives (2-4)",
                    "minimum": 2,
                    "maximum": 4,
                },
            },
            "required": ["topic"],
        },
        handler=execute,
        timeout=45,
    ))
