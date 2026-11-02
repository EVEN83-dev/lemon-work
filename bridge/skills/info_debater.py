import difflib
import textwrap

from .models import SkillResult, SkillDef

METADATA = {
    "name": "info_debater",
    "version": "1.0.0",
    "category": "reasoning",
    "description": "Generate structured debate arguments for or against a topic.",
}

_ARGUMENT_TEMPLATES_FOR = [
    ("Effectiveness", "The approach has demonstrated measurable positive outcomes in relevant contexts."),
    ("Efficiency", "Implementation requires reasonable resources relative to the expected benefits."),
    ("Precedent", "Similar approaches have been successfully adopted in comparable situations."),
    ("Scalability", "The proposed direction can grow and adapt to increasing demands."),
    ("Alignment", "The direction aligns with established best practices and stakeholder interests."),
    ("Evidence Base", "Empirical data and research findings support the proposed direction."),
    ("Cost-Benefit", "The projected benefits substantially outweigh the associated costs."),
]

_ARGUMENT_TEMPLATES_AGAINST = [
    ("Insufficient Evidence", "The supporting evidence is limited or lacks rigorous validation."),
    ("Unintended Consequences", "Implementation may produce negative side effects not yet identified."),
    ("Resource Burden", "The required investment of time, money, or effort is disproportionate."),
    ("Alternative Approaches", "Superior alternatives exist that achieve similar goals more effectively."),
    ("Implementation Risk", "Practical barriers may prevent successful execution of the approach."),
    ("Equity Concerns", "The approach may disproportionately disadvantage certain groups."),
    ("Sustainability", "Long-term viability of the approach has not been adequately demonstrated."),
]


def execute(topic: str, stance: str = "for", points: int = 5, **kwargs) -> SkillResult:
    stance = stance.lower()
    if stance not in ("for", "against"):
        return SkillResult.fail("stance must be 'for' or 'against'")

    points = max(3, min(7, points))

    templates = _ARGUMENT_TEMPLATES_FOR if stance == "for" else _ARGUMENT_TEMPLATES_AGAINST
    opposite = "against" if stance == "for" else "for"
    opp_templates = _ARGUMENT_TEMPLATES_AGAINST if stance == "for" else _ARGUMENT_TEMPLATES_FOR

    selected = templates[:points]
    opp_selected = opp_templates[:points]

    lines = []
    lines.append("=" * 60)
    lines.append("DEBATE ARGUMENT ANALYSIS")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Topic: " + topic)
    lines.append("Stance: " + stance.upper())
    lines.append("Arguments requested: " + str(points))
    lines.append("")

    lines.append("--- ARGUMENTS " + stance.upper() + " ---")
    lines.append("")
    for i, (label, template) in enumerate(selected, 1):
        lines.append("Argument " + str(i) + ": " + label)
        lines.append("-" * 40)
        claim = template.replace("The approach", topic).replace("The proposed direction", topic).replace("Implementation", "Implementing " + topic)
        lines.append("  Claim: " + claim)
        topic_words = topic.lower().split()
        keyword_evidence = "Supporting data points related to " + ", ".join(topic_words[:4]) + " reinforce this claim."
        lines.append("  Evidence: " + keyword_evidence)
        lines.append("  Reasoning: The claim follows from established patterns observed in similar domains.")
        opp_label, opp_template = opp_selected[i - 1] if i - 1 < len(opp_selected) else opp_selected[0]
        opp_claim = opp_template.replace("The approach", topic).replace("The proposed direction", topic).replace("Implementation", "Implementing " + topic)
        lines.append("  Anticipated Rebuttal (" + opposite + "): " + opp_claim)
        lines.append("  Preemptive Response: While the opposing view raises valid considerations, the weight of evidence still favors the " + stance + " position when all factors are considered.")
        lines.append("")

    lines.append("--- STRENGTH ASSESSMENT ---")
    lines.append("")
    strongest = selected[0]
    lines.append("Strongest argument " + stance + ": " + strongest[0])
    lines.append("  " + strongest[1].replace("The approach", topic).replace("The proposed direction", topic).replace("Implementation", "Implementing " + topic))
    weakest = selected[-1]
    lines.append("Weakest argument " + stance + ": " + weakest[0])
    lines.append("  " + weakest[1].replace("The approach", topic).replace("The proposed direction", topic).replace("Implementation", "Implementing " + topic))
    lines.append("  Vulnerability: The " + opposite + " side may target this with: " + opp_templates[-1][0])
    lines.append("")

    for_str = " ".join(t[1] for t in selected)
    against_str = " ".join(t[1] for t in opp_selected)
    similarity = difflib.SequenceMatcher(None, for_str, against_str).ratio()
    lines.append("--- ARGUMENT OVERLAP ANALYSIS (difflib) ---")
    lines.append("")
    lines.append("For/Against textual similarity ratio: " + str(round(similarity, 3)))
    if similarity > 0.5:
        lines.append("High overlap detected: Arguments share substantial terminology, making direct refutation important.")
    elif similarity > 0.3:
        lines.append("Moderate overlap: Some shared concepts but distinct framing on each side.")
    else:
        lines.append("Low overlap: Arguments operate in largely different conceptual spaces.")

    report = "\n".join(lines)

    return SkillResult.ok(
        output=report,
        data={
            "needs_llm": False,
            "topic": topic,
            "stance": stance,
            "points": points,
            "argument_labels": [t[0] for t in selected],
            "overlap_ratio": round(similarity, 3),
        },
    )


def register(registry) -> None:
    registry.register(SkillDef(
        name="info_debater",
        description="[DEPRECATED] Use business.info_debater instead. Legacy debate argument generator with difflib analysis.",
        category="reasoning",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Debate topic",
                },
                "stance": {
                    "type": "string",
                    "enum": ["for", "against"],
                    "description": "Which side to argue",
                },
                "points": {
                    "type": "integer",
                    "description": "Number of argument points (3-7)",
                    "minimum": 3,
                    "maximum": 7,
                },
            },
            "required": ["topic", "stance"],
        },
        handler=execute,
        timeout=30,
        deprecated=True,
        deprecation_message="Superseded by business.info_debater (multi-source comparison with difflib, keyword extraction, networkx graph, 4 modes).",
    ))
