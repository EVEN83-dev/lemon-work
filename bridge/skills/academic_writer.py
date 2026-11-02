import textwrap
from .models import SkillResult, SkillDef

METADATA = {
    "name": "academic_writer",
    "version": "1.0.0",
    "category": "writing",
    "description": "Academic paper writing assistant for various sections and citation styles.",
}


def execute(
    topic: str = "",
    section: str = "intro",
    style: str = "apa",
    word_count: int = 500,
    **kwargs,
) -> SkillResult:
    if not topic.strip():
        return SkillResult.fail("topic is required")

    valid_sections = ("abstract", "intro", "methods", "results", "discussion", "conclusion")
    if section not in valid_sections:
        return SkillResult.fail(f"Invalid section '{section}'. Must be one of: {valid_sections}")

    valid_styles = ("apa", "mla", "chicago")
    if style not in valid_styles:
        return SkillResult.fail(f"Invalid style '{style}'. Must be one of: {valid_styles}")

    if word_count <= 0 or word_count > 10000:
        return SkillResult.fail("word_count must be between 1 and 10000")

    style_names = {"apa": "APA 7th Edition", "mla": "MLA 9th Edition", "chicago": "Chicago 17th Edition"}

    section_templates = {
        "abstract": _build_abstract,
        "intro": _build_intro,
        "methods": _build_methods,
        "results": _build_results,
        "discussion": _build_discussion,
        "conclusion": _build_conclusion,
    }

    output = section_templates[section](topic, style, style_names[style], word_count)
    return SkillResult.ok(output=output, data={"needs_llm": False, "topic": topic, "section": section, "style": style, "word_count": word_count})


def _citation_template(style: str) -> str:
    if style == "apa":
        return "(Author, Year)" 
    if style == "mla":
        return "(Author Page)"
    return "(Author Year, Page)"


def _reference_header(style: str) -> str:
    if style == "apa":
        return "References"
    if style == "mla":
        return "Works Cited"
    return "Bibliography"


def _build_abstract(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Abstract",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## Structure",
        f"",
        f"1. **Research Context** (2-3 sentences)",
        f"   Broad context of the research area. {cite}",
        f"",
        f"2. **Research Problem** (1-2 sentences)",
        f"   Specific gap or problem this study addresses.",
        f"",
        f"3. **Methodology** (2-3 sentences)",
        f"   Brief description of the research design and methods.",
        f"",
        f"4. **Key Findings** (2-3 sentences)",
        f"   Summary of the most significant results.",
        f"",
        f"5. **Significance** (1-2 sentences)",
        f"   Implications and contribution to the field.",
        f"",
        f"## Keywords",
        f"",
        f"- {topic}",
        f"- [Add 3-5 relevant keywords]",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def _build_intro(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Introduction",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## 1. Research Background",
        f"",
        f"Establish the broader context of {topic}. Provide foundational",
        f"knowledge that a reader needs to understand the research problem.",
        f"{cite}",
        f"",
        f"## 2. Problem Statement",
        f"",
        f"Articulate the specific problem or research question:",
        f"- What is the core issue?",
        f"- Why does it matter?",
        f"- Who is affected?",
        f"",
        f"## 3. Literature Review Context",
        f"",
        f"Summarize key prior work:",
        f"- Study A: Finding {cite}",
        f"- Study B: Finding {cite}",
        f"- Study C: Finding {cite}",
        f"- Identify consensus and disagreements",
        f"",
        f"## 4. Research Gaps",
        f"",
        f"Identify what existing literature does NOT address:",
        f"- Gap 1: [Description]",
        f"- Gap 2: [Description]",
        f"",
        f"## 5. Objectives and Hypotheses",
        f"",
        f"State the research objectives:",
        f"- Objective 1: [Description]",
        f"- Objective 2: [Description]",
        f"",
        f"Hypotheses (if applicable):",
        f"- H1: [Statement]",
        f"- H2: [Statement]",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def _build_methods(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Methodology",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## 1. Research Design",
        f"",
        f"- Design type: [Experimental / Quasi-experimental / Correlational / Descriptive / Mixed-methods]",
        f"- Approach: [Quantitative / Qualitative / Mixed]",
        f"- Rationale for design choice {cite}",
        f"",
        f"## 2. Participants / Sample",
        f"",
        f"- Population: [Description]",
        f"- Sample size: [N = ?]",
        f"- Sampling method: [Random / Stratified / Convenience / Purposive]",
        f"- Inclusion/exclusion criteria: [List]",
        f"- Demographic characteristics: [Table placeholder]",
        f"",
        f"## 3. Data Collection Procedures",
        f"",
        f"- Instruments: [Surveys / Interviews / Observations / Archival]",
        f"- Procedure timeline:",
        f"  1. Phase 1: [Description]",
        f"  2. Phase 2: [Description]",
        f"  3. Phase 3: [Description]",
        f"- Reliability and validity measures {cite}",
        f"",
        f"## 4. Analytical Methods",
        f"",
        f"- Statistical tests: [t-test / ANOVA / Regression / Thematic analysis / etc.]",
        f"- Software used: [SPSS / R / NVivo / etc.]",
        f"- Significance level: [alpha = 0.05]",
        f"",
        f"## 5. Ethical Considerations",
        f"",
        f"- IRB/Ethics board approval: [Reference number]",
        f"- Informed consent procedures",
        f"- Data anonymization and storage",
        f"- Potential risks and mitigation",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def _build_results(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Results",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## 1. Descriptive Statistics",
        f"",
        f"| Variable | N | Mean | SD | Min | Max |",
        f"|----------|---|------|----|-----|-----|",
        f"| [Var 1]  |   |      |    |     |     |",
        f"| [Var 2]  |   |      |    |     |     |",
        f"",
        f"## 2. Key Findings",
        f"",
        f"### Finding 1: [Title]",
        f"- Statistical result: [t(df) = X, p = Y]",
        f"- Effect size: [Cohen's d / eta-squared / etc.]",
        f"- Interpretation {cite}",
        f"",
        f"### Finding 2: [Title]",
        f"- Statistical result: [F(df1, df2) = X, p = Y]",
        f"- Effect size: [Value]",
        f"- Interpretation {cite}",
        f"",
        f"## 3. Table and Figure Descriptions",
        f"",
        f"- Table 1: [Description]",
        f"- Table 2: [Description]",
        f"- Figure 1: [Description]",
        f"",
        f"## 4. Additional Analyses",
        f"",
        f"- [Post-hoc tests / Subgroup analyses / Sensitivity analyses]",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def _build_discussion(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Discussion",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## 1. Interpretation of Results",
        f"",
        f"- Summarize key findings without repeating statistics",
        f"- Explain what the results mean in context of {topic}",
        f"- Relate to research objectives and hypotheses",
        f"",
        f"## 2. Comparison with Prior Research",
        f"",
        f"- Finding 1 aligns with Study A {cite}",
        f"- Finding 2 contrasts with Study B {cite}",
        f"- Novel contributions of this study",
        f"",
        f"## 3. Theoretical Implications",
        f"",
        f"- How results support/challenge existing theories",
        f"- Proposed theoretical refinements",
        f"",
        f"## 4. Practical Implications",
        f"",
        f"- Recommendations for practitioners",
        f"- Policy implications (if applicable)",
        f"- Applied significance",
        f"",
        f"## 5. Limitations",
        f"",
        f"- Limitation 1: [Description and impact]",
        f"- Limitation 2: [Description and impact]",
        f"- Limitation 3: [Description and impact]",
        f"",
        f"## 6. Future Directions",
        f"",
        f"- Suggested replication studies",
        f"- Extensions to other populations/contexts",
        f"- Methodological improvements",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def _build_conclusion(topic: str, style: str, style_full: str, wc: int) -> str:
    cite = _citation_template(style)
    lines = [
        f"# Conclusion",
        f"",
        f"**Topic:** {topic}",
        f"**Citation Style:** {style_full}",
        f"**Target Length:** {wc} words",
        f"",
        f"## 1. Key Takeaways",
        f"",
        f"- Takeaway 1: [Summary of most important finding]",
        f"- Takeaway 2: [Summary of second finding]",
        f"- Takeaway 3: [Summary of third finding]",
        f"",
        f"## 2. Contributions",
        f"",
        f"- Theoretical contribution: [How this advances knowledge]",
        f"- Empirical contribution: [New data/evidence provided]",
        f"- Methodological contribution: [Innovative approaches used]",
        f"",
        f"## 3. Practical Implications",
        f"",
        f"- For [Stakeholder A]: [Recommendation]",
        f"- For [Stakeholder B]: [Recommendation]",
        f"- For [Stakeholder C]: [Recommendation]",
        f"",
        f"## 4. Closing Remarks",
        f"",
        f"Restate the significance of the study on {topic}.",
        f"Emphasize the broader impact and final thought.",
        f"",
        f"## {_reference_header(style)}",
        f"",
        f"- [Author, A. (Year). Title. Journal. {cite}]",
    ]
    return "\n".join(lines)


def register(registry) -> None:
    registry.register(SkillDef(
        name="academic_writer",
        description="Academic paper writing assistant for various sections (abstract, intro, methods, etc.) with APA/MLA/Chicago styles.",
        category="writing",
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Research topic for the academic paper",
                },
                "section": {
                    "type": "string",
                    "enum": ["abstract", "intro", "methods", "results", "discussion", "conclusion"],
                    "description": "Paper section to write",
                },
                "style": {
                    "type": "string",
                    "enum": ["apa", "mla", "chicago"],
                    "description": "Citation and formatting style",
                },
                "word_count": {
                    "type": "integer",
                    "description": "Target word count for the section",
                },
            },
            "required": ["topic"],
        },
        handler=execute,
        timeout=60,
    ))
