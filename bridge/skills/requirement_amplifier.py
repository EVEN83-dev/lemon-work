from .models import SkillResult, SkillDef

import re
import json
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

METADATA = {
    "name": "requirement_amplifier",
    "version": "2.0.0",
    "category": "analysis",
    "description": "Expand brief requirements into detailed specifications.",
}

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might must can could of in on at to "
    "for with by from and or but not no nor so if then than too very "
    "just about above after again all also am as because before below "
    "between both each few here how into more most other our out over "
    "own same some such that this these those through under until up "
    "what when where which while who whom why it its i me my we us "
    "you your he him his she her they them their what which who whom "
    "this that these those any each every all both few many several "
    "some none one two three four five six seven eight nine ten "
    "make get let set put use need want go come take give find tell "
    "work call try ask seem feel leave keep begin show hear play run "
    "move live believe happen bring become remain represent require".split()
)

_ACTION_VERBS = frozenset(
    "create read update delete manage generate process validate "
    "authenticate authorize configure deploy monitor export import "
    "search filter sort paginate track log notify schedule calculate "
    "transform convert parse format serialize deserialize encrypt "
    "decrypt compress decompress upload download sync migrate "
    "register unregister subscribe unsubscribe enable disable "
    "activate deactivate assign revoke grant deny approve reject "
    "submit accept cancel resume pause retry rollback commit "
    "checkout render redirect route handle trigger dispatch "
    "emit listen watch observe measure report aggregate "
    "store retrieve query index cache batch stream ".split()
)

_ROLE_PATTERNS = [
    (r"\buser\b", "User"),
    (r"\badmin(?:istrator)?\b", "Administrator"),
    (r"\bmanager\b", "Manager"),
    (r"\bowner\b", "Owner"),
    (r"\bguest\b", "Guest"),
    (r"\bmember\b", "Member"),
    (r"\bcustomer\b", "Customer"),
    (r"\bclient\b", "Client"),
    (r"\boperator\b", "Operator"),
    (r"\bdeveloper\b", "Developer"),
    (r"\banalyst\b", "Analyst"),
    (r"\bmoderator\b", "Moderator"),
    (r"\bauditor\b", "Auditor"),
    (r"\btester\b", "Tester"),
    (r"\bviewer\b", "Viewer"),
    (r"\bcontributor\b", "Contributor"),
    (r"\bauthor\b", "Author"),
    (r"\beditor\b", "Editor"),
    (r"\bpublisher\b", "Publisher"),
    (r"\bsubscriber\b", "Subscriber"),
    (r"\bvendor\b", "Vendor"),
    (r"\bprovider\b", "Provider"),
    (r"\bconsumer\b", "Consumer"),
    (r"\bagent\b", "Agent"),
    (r"\bsuper(?:user|admin)\b", "Super Administrator"),
]

_CONSTRAINT_KEYWORDS = frozenset(
    "must shall should may cannot never always only within "
    "before after during while ensure guarantee enforce "
    "restrict limit require allow deny prevent support "
    "exclude include at least at most minimum maximum "
    "exactly between per each every".split()
)

_NFR_CATEGORIES = OrderedDict([
    ("Performance", ["response time", "throughput", "latency", "concurrent users", "load capacity"]),
    ("Reliability", ["uptime", "fault tolerance", "recovery time", "data durability", "backup"]),
    ("Security", ["authentication", "authorization", "encryption", "audit trail", "data protection"]),
    ("Usability", ["accessibility", "learnability", "error tolerance", "response feedback"]),
    ("Scalability", ["horizontal scaling", "vertical scaling", "data growth", "user growth"]),
    ("Maintainability", ["modularity", "testability", "documentation", "code quality"]),
    ("Compatibility", ["browser support", "platform support", "API versioning", "backward compatibility"]),
])


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text.lower())


def _extract_key_phrases(text: str) -> List[str]:
    sentences = re.split(r'[.!?;]\s*', text)
    phrases = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        chunks = re.split(r'\b(?:and|or|but|however|also|additionally|furthermore|moreover|therefore|thus|so|then)\b', s, flags=re.IGNORECASE)
        for chunk in chunks:
            chunk = chunk.strip()
            chunk = re.sub(r'^\s*(?:the|a|an|this|that|these|those|it|its|they|their)\b', '', chunk, flags=re.IGNORECASE).strip()
            if len(chunk) > 3:
                phrases.append(chunk)
    return phrases


def _extract_entities(text: str) -> List[Dict[str, Any]]:
    tokens = _tokenize(text)
    entities = OrderedDict()
    for tok in tokens:
        if tok in _STOP_WORDS:
            continue
        if tok in _ACTION_VERBS:
            continue
        if tok in _CONSTRAINT_KEYWORDS:
            continue
        if len(tok) <= 2:
            continue
        if tok not in entities:
            entities[tok] = {
                "name": tok.title(),
                "occurrences": 0,
                "likely_type": _guess_entity_type(tok, text),
            }
        entities[tok]["occurrences"] += 1

    sorted_ents = sorted(entities.values(), key=lambda e: e["occurrences"], reverse=True)
    return sorted_ents[:15]


def _guess_entity_type(word: str, context: str) -> str:
    if re.search(r'\b' + word + r'\s+(?:list|collection|set|array|items?)\b', context, re.IGNORECASE):
        return "collection"
    if re.search(r'\b(?:list|collection|set|array|items?)\s+of\s+' + word + r'\b', context, re.IGNORECASE):
        return "collection"
    if word.endswith("tion") or word.endswith("sion"):
        return "process"
    if word.endswith("ment"):
        return "artifact"
    if word.endswith("er") or word.endswith("or"):
        return "actor"
    if word.endswith("ity") or word.endswith("ness"):
        return "attribute"
    if word.endswith("log") or word.endswith("record") or word.endswith("history"):
        return "log"
    if word.endswith("config") or word.endswith("setting") or word.endswith("preference"):
        return "configuration"
    return "entity"


def _extract_actions(text: str) -> List[str]:
    found = []
    for verb in sorted(_ACTION_VERBS):
        if re.search(r'\b' + verb + r'\b', text, re.IGNORECASE):
            found.append(verb)
    for m in re.finditer(r'\b([a-z]+(?:ed|ing|ize|ify|ate|en))\b', text, re.IGNORECASE):
        w = m.group(1).lower()
        if w not in _STOP_WORDS and len(w) > 3:
            stem = re.sub(r'(?:ed|ing|ize|ify|ate|en)$', '', w)
            if stem and stem not in found:
                found.append(stem)
    return found[:20]


def _extract_constraints(text: str) -> List[Dict[str, str]]:
    constraints = []
    for kw in sorted(_CONSTRAINT_KEYWORDS):
        for m in re.finditer(r'\b' + kw + r'\b(.{0,80})', text, re.IGNORECASE):
            fragment = m.group(1).strip()
            fragment = re.sub(r'[.;,]\s*$', '', fragment).strip()
            if fragment:
                constraints.append({"keyword": kw, "context": fragment})
    return constraints[:12]


def _extract_roles(text: str) -> List[str]:
    roles = ["User"]
    for pattern, role_name in _ROLE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            if role_name not in roles:
                roles.append(role_name)
    return roles


def _generate_user_stories(
    key_phrases: List[str],
    entities: List[Dict[str, Any]],
    actions: List[str],
    roles: List[str],
    detail_level: int,
) -> List[Dict[str, str]]:
    stories = []
    story_id = 0

    for action in actions:
        for role in roles[:max(1, detail_level)]:
            story_id += 1
            benefit = _infer_benefit(action, role)
            stories.append({
                "id": f"US-{story_id:03d}",
                "role": role,
                "action": action,
                "benefit": benefit,
                "story": f"As a {role}, I want to {action}, so that {benefit}",
            })

    if detail_level >= 2:
        for entity in entities[:detail_level * 2]:
            for action in actions[:2]:
                story_id += 1
                benefit = _infer_benefit(action, entity["name"])
                stories.append({
                    "id": f"US-{story_id:03d}",
                    "role": "User",
                    "action": f"{action} {entity['name'].lower()}",
                    "benefit": benefit,
                    "story": f"As a User, I want to {action} {entity['name'].lower()}, so that {benefit}",
                })

    if detail_level >= 4:
        implicit = _infer_implicit_stories(entities, actions, roles)
        for imp in implicit:
            story_id += 1
            stories.append({
                "id": f"US-{story_id:03d}",
                "role": imp["role"],
                "action": imp["action"],
                "benefit": imp["benefit"],
                "story": f"As a {imp['role']}, I want to {imp['action']}, so that {imp['benefit']}",
            })

    return stories[:detail_level * 8]


def _infer_benefit(action: str, role: str) -> str:
    benefits = {
        "create": "I can add new data to the system",
        "read": "I can view the information I need",
        "update": "I can keep information current and accurate",
        "delete": "I can remove outdated or incorrect data",
        "manage": "I can maintain control over system resources",
        "generate": "I can produce needed outputs automatically",
        "process": "I can transform inputs into useful results",
        "validate": "I can ensure data correctness and integrity",
        "authenticate": "I can verify identity securely",
        "authorize": "I can control access to protected resources",
        "search": "I can find relevant information quickly",
        "filter": "I can focus on specific subsets of data",
        "sort": "I can organize information in a meaningful order",
        "notify": "I can receive timely alerts about important events",
        "schedule": "I can plan and coordinate activities over time",
        "export": "I can use data in external systems and reports",
        "import": "I can bring existing data into the system",
        "track": "I can monitor progress and changes",
        "log": "I can maintain a record of system activities",
        "monitor": "I can observe system health and performance",
        "configure": "I can customize the system to meet my needs",
        "deploy": "I can release changes to production reliably",
        "subscribe": "I can receive updates on topics of interest",
        "register": "I can create an account and access the system",
        "enable": "I can activate features as needed",
        "disable": "I can turn off features that are not required",
        "assign": "I can allocate resources to the right recipients",
        "approve": "I can confirm actions before they take effect",
        "reject": "I can prevent invalid or unwanted actions",
        "submit": "I can send data for processing or review",
        "cancel": "I can abort operations that are no longer needed",
        "retry": "I can recover from transient failures",
    }
    return benefits.get(action, f"I can accomplish my goals using {action}")


def _infer_implicit_stories(
    entities: List[Dict[str, Any]],
    actions: List[str],
    roles: List[str],
) -> List[Dict[str, str]]:
    implicit = []
    has_create = "create" in actions
    has_read = "read" in actions or "search" in actions
    has_update = "update" in actions
    has_delete = "delete" in actions

    if any([has_create, has_read, has_update, has_delete]) and "manage" not in actions:
        implicit.append({"role": roles[0], "action": "manage data lifecycle (CRUD)", "benefit": "I can maintain complete control over data"})

    if has_create or has_update:
        implicit.append({"role": roles[0], "action": "validate input data", "benefit": "I can prevent errors and data corruption"})

    if len(entities) >= 2:
        implicit.append({"role": roles[0], "action": "view relationships between entities", "benefit": "I can understand how data connects"})

    if "Administrator" in roles or len(roles) > 1:
        implicit.append({"role": "Administrator", "action": "configure access permissions", "benefit": "I can enforce security policies"})

    if "authenticate" not in actions and len(roles) > 1:
        implicit.append({"role": roles[0], "action": "authenticate my identity", "benefit": "I can securely access the system"})

    implicit.append({"role": roles[0], "action": "receive error messages when operations fail", "benefit": "I can understand and correct problems"})

    return implicit


def _infer_implicit_requirements(
    actions: List[str],
    entities: List[Dict[str, Any]],
    constraints: List[Dict[str, str]],
    roles: List[str],
) -> List[Dict[str, str]]:
    implicit = []
    if "create" in actions or "update" in actions:
        implicit.append({"category": "functional", "requirement": "Input validation for all user-provided data"})
        implicit.append({"category": "functional", "requirement": "Error messages for invalid submissions"})
    if "delete" in actions:
        implicit.append({"category": "functional", "requirement": "Confirmation prompt before destructive operations"})
        implicit.append({"category": "data", "requirement": "Soft delete or archival strategy for recoverability"})
    if len(roles) > 1:
        implicit.append({"category": "security", "requirement": "Role-based access control for differentiated permissions"})
    if "authenticate" in actions or "authorize" in actions:
        implicit.append({"category": "security", "requirement": "Session management and token expiration"})
    if "search" in actions or "filter" in actions:
        implicit.append({"category": "performance", "requirement": "Indexed search for responsive query performance"})
    if len(entities) >= 3:
        implicit.append({"category": "data", "requirement": "Referential integrity between related entities"})
    if "export" in actions:
        implicit.append({"category": "functional", "requirement": "Multiple export formats (CSV, JSON, PDF)"})
    if "notify" in actions:
        implicit.append({"category": "functional", "requirement": "Notification delivery guarantee and retry mechanism"})
    implicit.append({"category": "non-functional", "requirement": "Audit logging for all state-changing operations"})
    implicit.append({"category": "non-functional", "requirement": "Graceful degradation under high load"})
    return implicit


def _generate_data_models(
    entities: List[Dict[str, Any]],
    actions: List[str],
    detail_level: int,
) -> List[Dict[str, Any]]:
    models = []
    has_crud = any(v in actions for v in ["create", "read", "update", "delete", "manage"])

    for i, entity in enumerate(entities[:detail_level * 3]):
        model_name = entity["name"].replace(" ", "")
        attributes = _infer_attributes(entity, actions, detail_level)
        relationships = _infer_relationships(entity, entities, i, detail_level)

        model = {
            "name": model_name,
            "type": entity["likely_type"],
            "attributes": attributes,
        }
        if relationships and detail_level >= 2:
            model["relationships"] = relationships
        models.append(model)

    if has_crud and detail_level >= 3:
        for suffix in ["AuditLog", "Configuration", "Notification"]:
            if not any(m["name"].endswith(suffix) for m in models):
                models.append({
                    "name": suffix,
                    "type": "system",
                    "attributes": _infer_system_attributes(suffix),
                    "relationships": [{"target": entities[0]["name"].replace(" ", ""), "type": "references"}] if entities else [],
                })

    return models


def _infer_attributes(entity: Dict[str, Any], actions: List[str], detail_level: int) -> List[Dict[str, str]]:
    attrs = [
        {"name": "id", "type": "string", "constraint": "primary key"},
        {"name": "createdAt", "type": "datetime", "constraint": "auto-generated"},
        {"name": "updatedAt", "type": "datetime", "constraint": "auto-updated"},
    ]
    name = entity["name"].lower()

    if entity["likely_type"] == "actor":
        attrs.extend([
            {"name": "name", "type": "string", "constraint": "required"},
            {"name": "email", "type": "string", "constraint": "required, unique"},
        ])
    elif entity["likely_type"] == "process":
        attrs.extend([
            {"name": "status", "type": "enum", "constraint": "pending|active|completed|failed"},
            {"name": "triggeredBy", "type": "string", "constraint": "optional"},
        ])
    elif entity["likely_type"] == "configuration":
        attrs.extend([
            {"name": "key", "type": "string", "constraint": "required, unique"},
            {"name": "value", "type": "string", "constraint": "required"},
        ])
    else:
        attrs.extend([
            {"name": f"{name}Name", "type": "string", "constraint": "required"},
            {"name": "description", "type": "text", "constraint": "optional"},
        ])

    if "validate" in actions or detail_level >= 4:
        attrs.append({"name": "isValid", "type": "boolean", "constraint": "computed"})

    if detail_level >= 3:
        attrs.extend([
            {"name": "createdBy", "type": "string", "constraint": "optional"},
            {"name": "version", "type": "integer", "constraint": "auto-incremented"},
        ])

    return attrs


def _infer_system_attributes(model_name: str) -> List[Dict[str, str]]:
    if model_name == "AuditLog":
        return [
            {"name": "id", "type": "string", "constraint": "primary key"},
            {"name": "entityType", "type": "string", "constraint": "required"},
            {"name": "entityId", "type": "string", "constraint": "required"},
            {"name": "action", "type": "string", "constraint": "required"},
            {"name": "performedBy", "type": "string", "constraint": "required"},
            {"name": "timestamp", "type": "datetime", "constraint": "auto-generated"},
            {"name": "details", "type": "text", "constraint": "optional"},
        ]
    if model_name == "Configuration":
        return [
            {"name": "id", "type": "string", "constraint": "primary key"},
            {"name": "key", "type": "string", "constraint": "required, unique"},
            {"name": "value", "type": "string", "constraint": "required"},
            {"name": "updatedAt", "type": "datetime", "constraint": "auto-updated"},
        ]
    if model_name == "Notification":
        return [
            {"name": "id", "type": "string", "constraint": "primary key"},
            {"name": "recipientId", "type": "string", "constraint": "required"},
            {"name": "type", "type": "enum", "constraint": "info|warning|error"},
            {"name": "message", "type": "text", "constraint": "required"},
            {"name": "read", "type": "boolean", "constraint": "default false"},
            {"name": "createdAt", "type": "datetime", "constraint": "auto-generated"},
        ]
    return []


def _infer_relationships(
    entity: Dict[str, Any],
    all_entities: List[Dict[str, Any]],
    index: int,
    detail_level: int,
) -> List[Dict[str, str]]:
    rels = []
    if index == 0 and len(all_entities) > 1:
        for other in all_entities[1:detail_level]:
            rels.append({"target": other["name"].replace(" ", ""), "type": "has many"})
    elif index > 0:
        rels.append({"target": all_entities[0]["name"].replace(" ", ""), "type": "belongs to"})
    return rels


def _generate_nfrs(constraints: List[Dict[str, str]], detail_level: int) -> List[Dict[str, str]]:
    nfrs = []
    for cat, indicators in _NFR_CATEGORIES.items():
        matched = []
        for indicator in indicators:
            for c in constraints:
                if indicator.replace(" ", "") in c["context"].replace(" ", "").lower():
                    matched.append(indicator)
                    break
        if not matched and detail_level < 4:
            if cat in ("Performance", "Security", "Reliability"):
                matched = indicators[:1]
            else:
                continue
        if not matched:
            matched = indicators[:max(1, detail_level - 2)]

        for m in matched[:detail_level]:
            nfrs.append({"category": cat, "requirement": f"System must address {m}"})

    return nfrs


def _generate_test_scenarios(
    stories: List[Dict[str, str]],
    actions: List[str],
    entities: List[Dict[str, Any]],
    detail_level: int,
) -> List[Dict[str, str]]:
    scenarios = []
    tc_id = 0

    for story in stories[:detail_level * 3]:
        tc_id += 1
        scenarios.append({
            "id": f"TC-{tc_id:03d}",
            "type": "happy path",
            "description": f"Verify: {story['story']}",
            "steps": _happy_path_steps(story["action"]),
        })
        if detail_level >= 3:
            tc_id += 1
            scenarios.append({
                "id": f"TC-{tc_id:03d}",
                "type": "negative",
                "description": f"Verify failure handling when {story['action']} with invalid input",
                "steps": ["Provide invalid or missing input", "Submit the operation", "Verify error response", "Verify no side effects"],
            })

    if detail_level >= 4:
        tc_id += 1
        scenarios.append({
            "id": f"TC-{tc_id:03d}",
            "type": "boundary",
            "description": "Verify behavior at input boundaries (empty, max length, special characters)",
            "steps": ["Prepare boundary test data", "Execute operation", "Verify correct handling or rejection"],
        })
        if len(entities) >= 2:
            tc_id += 1
            scenarios.append({
                "id": f"TC-{tc_id:03d}",
                "type": "integration",
                "description": "Verify data consistency across related entities",
                "steps": ["Create parent entity", "Create child entity linked to parent", "Verify relationship integrity", "Delete parent and verify cascade behavior"],
            })

    if detail_level >= 5:
        tc_id += 1
        scenarios.append({
            "id": f"TC-{tc_id:03d}",
            "type": "performance",
            "description": "Verify acceptable response times under expected load",
            "steps": ["Generate representative load", "Execute operations concurrently", "Measure response times", "Verify within acceptable thresholds"],
        })
        tc_id += 1
        scenarios.append({
            "id": f"TC-{tc_id:03d}",
            "type": "security",
            "description": "Verify access control enforcement and data protection",
            "steps": ["Attempt operation without authentication", "Attempt operation with insufficient permissions", "Verify proper rejection", "Verify audit log entries"],
        })

    return scenarios


def _happy_path_steps(action: str) -> List[str]:
    templates = {
        "create": ["Prepare valid input data", "Submit creation request", "Verify entity is created", "Verify stored data matches input"],
        "read": ["Ensure target entity exists", "Request entity data", "Verify correct data returned", "Verify response format"],
        "update": ["Ensure target entity exists", "Prepare updated data", "Submit update request", "Verify entity reflects changes"],
        "delete": ["Ensure target entity exists", "Submit deletion request", "Verify entity is removed", "Verify no dangling references"],
        "search": ["Populate test data", "Execute search with known criteria", "Verify matching results returned", "Verify result ordering and pagination"],
        "authenticate": ["Provide valid credentials", "Submit authentication request", "Verify session or token issued", "Verify protected resource accessible"],
        "authorize": ["Create user with specific role", "Attempt allowed operation", "Attempt disallowed operation", "Verify correct access control"],
        "validate": ["Prepare valid input", "Prepare invalid input", "Submit both", "Verify valid accepted, invalid rejected with clear message"],
        "notify": ["Trigger notification event", "Verify notification generated", "Verify notification delivered", "Verify notification content correct"],
        "export": ["Populate data for export", "Request export", "Verify file generated", "Verify exported data completeness"],
    }
    for key in templates:
        if key in action.lower():
            return templates[key]
    return ["Prepare prerequisite data", "Execute the operation", "Verify expected outcome", "Verify no unintended side effects"]


def _score_requirement(
    requirement: str,
    entities: List[Dict[str, Any]],
    actions: List[str],
    constraints: List[Dict[str, str]],
    roles: List[str],
) -> Dict[str, Any]:
    scores = {}
    word_count = len(requirement.split())
    scores["specificity"] = min(100, len(entities) * 10 + len(actions) * 5)
    scores["completeness"] = min(100,
        (20 if len(actions) >= 2 else len(actions) * 10)
        + (20 if len(entities) >= 2 else len(entities) * 10)
        + (20 if len(constraints) >= 1 else 0)
        + (20 if len(roles) >= 2 else 10)
        + (20 if word_count >= 20 else word_count)
    )
    scores["testability"] = min(100, len(actions) * 15 + len(constraints) * 10)
    scores["clarity"] = min(100, 80 if word_count >= 10 else word_count * 8)
    if not actions:
        scores["clarity"] = max(0, scores["clarity"] - 30)
    if not entities:
        scores["specificity"] = max(0, scores["specificity"] - 30)

    overall = int(sum(scores.values()) / len(scores))
    gaps = []
    if not actions:
        gaps.append("No explicit actions or verbs identified -- consider specifying what users can do")
    if not constraints:
        gaps.append("No constraints or validation rules stated -- consider adding must/shall/should qualifiers")
    if len(roles) <= 1:
        gaps.append("Only one role identified -- consider whether different user types have different needs")
    if word_count < 15:
        gaps.append("Requirement is very brief -- more detail would improve clarity")
    if len(entities) == 0:
        gaps.append("No key domain entities identified -- consider naming the data or objects involved")

    return {
        "overall": overall,
        "breakdown": scores,
        "gaps": gaps,
    }


def _build_markdown(
    requirement: str,
    detail_level: int,
    entities: List[Dict[str, Any]],
    actions: List[str],
    constraints: List[Dict[str, str]],
    roles: List[str],
    key_phrases: List[str],
    stories: List[Dict[str, str]],
    implicit_reqs: List[Dict[str, str]],
    data_models: List[Dict[str, Any]],
    nfrs: List[Dict[str, str]],
    test_scenarios: List[Dict[str, str]],
    score: Dict[str, Any],
) -> str:
    lines = []
    lines.append("# Requirement Amplification Report")
    lines.append("")
    lines.append(f"**Original Requirement:** {requirement}")
    lines.append(f"**Detail Level:** {detail_level}/5")
    lines.append(f"**Clarity Score:** {score['overall']}/100")
    lines.append("")

    if score["gaps"]:
        lines.append("## 0. Clarity Gaps")
        lines.append("")
        for gap in score["gaps"]:
            lines.append(f"- {gap}")
        lines.append("")

    lines.append("## 1. Overview")
    lines.append("")
    lines.append("### Problem Statement")
    lines.append(f"The requirement addresses the need for {', '.join(e['name'].lower() for e in entities[:5]) or 'the described functionality'}.")
    lines.append("")
    lines.append("### Goals and Objectives")
    for action in actions[:5]:
        lines.append(f"- Enable {action} capabilities")
    lines.append("")
    lines.append("### Scope and Boundaries")
    if constraints:
        lines.append("The following constraints define the scope:")
        for c in constraints[:5]:
            lines.append(f"- [{c['keyword']}] {c['context']}")
    else:
        lines.append("No explicit constraints were stated in the original requirement.")
    lines.append("")

    lines.append("## 2. Functional Requirements")
    lines.append("")
    lines.append("### Core Features (Must-Have)")
    for action in actions[:5]:
        lines.append(f"- Ability to {action}")
    lines.append("")
    if detail_level >= 2:
        lines.append("### Secondary Features (Should-Have)")
        for action in actions[5:8]:
            lines.append(f"- Ability to {action}")
        if len(actions) <= 5:
            lines.append("- Input validation and error reporting")
            lines.append("- Search and filtering capabilities")
        lines.append("")
    if detail_level >= 3:
        lines.append("### Optional Features (Nice-to-Have)")
        lines.append("- Bulk operations")
        lines.append("- Customizable preferences")
        lines.append("- Advanced analytics and reporting")
        lines.append("")

    lines.append("## 3. User Stories")
    lines.append("")
    for story in stories:
        lines.append(f"- **{story['id']}**: {story['story']}")
    lines.append("")

    if detail_level >= 2:
        lines.append("## 4. Non-Functional Requirements")
        lines.append("")
        for nfr in nfrs:
            lines.append(f"- [{nfr['category']}] {nfr['requirement']}")
        lines.append("")

        lines.append("## 5. Constraints")
        lines.append("")
        if constraints:
            for c in constraints:
                lines.append(f"- **{c['keyword']}**: {c['context']}")
        else:
            lines.append("- No explicit constraints stated")
        lines.append("")

    if detail_level >= 2:
        lines.append("## 6. Implicit Requirements")
        lines.append("")
        for imp in implicit_reqs:
            lines.append(f"- [{imp['category']}] {imp['requirement']}")
        lines.append("")

    if detail_level >= 3:
        lines.append("## 7. Data Models")
        lines.append("")
        for model in data_models:
            lines.append(f"### {model['name']} ({model['type']})")
            lines.append("")
            lines.append("| Attribute | Type | Constraint |")
            lines.append("|-----------|------|------------|")
            for attr in model["attributes"]:
                lines.append(f"| {attr['name']} | {attr['type']} | {attr['constraint']} |")
            if "relationships" in model and model["relationships"]:
                lines.append("")
                lines.append("**Relationships:**")
                for rel in model["relationships"]:
                    lines.append(f"- {rel['type']} -> {rel['target']}")
            lines.append("")

    if detail_level >= 4:
        lines.append("## 8. API Considerations")
        lines.append("")
        for action in actions[:6]:
            method_map = {
                "create": "POST", "read": "GET", "update": "PUT",
                "delete": "DELETE", "search": "GET", "list": "GET",
                "validate": "POST", "authenticate": "POST", "authorize": "POST",
                "export": "GET", "import": "POST",
            }
            method = method_map.get(action, "POST")
            lines.append(f"- `{method} /api/{action}` -- {action.capitalize()} operation")
        lines.append("")

        lines.append("## 9. Error Handling")
        lines.append("")
        error_scenarios = [
            "Invalid or missing input parameters",
            "Resource not found",
            "Permission denied",
            "Concurrent modification conflict",
            "Service unavailable or timeout",
        ]
        for i, err in enumerate(error_scenarios[:detail_level], 1):
            lines.append(f"{i}. **{err}**: Return structured error response with code, message, and remediation hint")
        lines.append("")

        lines.append("## 10. Security Considerations")
        lines.append("")
        sec_items = ["Input sanitization to prevent injection attacks", "Authentication required for all mutating operations"]
        if len(roles) > 1:
            sec_items.append("Role-based authorization checks on every endpoint")
        sec_items.extend(["HTTPS enforcement for all communications", "Sensitive data encryption at rest and in transit"])
        for item in sec_items:
            lines.append(f"- {item}")
        lines.append("")

    if detail_level >= 5:
        lines.append("## 11. Scalability and Performance")
        lines.append("")
        lines.append("- Design for horizontal scaling with stateless services")
        lines.append("- Implement caching layer for frequently accessed data")
        lines.append("- Use asynchronous processing for long-running operations")
        lines.append("- Database indexing strategy based on query patterns")
        lines.append("- Pagination for all list/query endpoints")
        lines.append("")

        lines.append("## 12. Testing Strategy")
        lines.append("")

        lines.append("### Test Scenarios")
        lines.append("")
        for tc in test_scenarios:
            lines.append(f"**{tc['id']}** [{tc['type']}]")
            lines.append(f"- {tc['description']}")
            lines.append("- Steps:")
            for step in tc["steps"]:
                lines.append(f"  1. {step}")
            lines.append("")

        lines.append("### Acceptance Criteria")
        lines.append("")
        lines.append("- All happy-path test scenarios pass")
        lines.append("- All negative test scenarios produce appropriate error responses")
        lines.append("- No data corruption under concurrent access")
        lines.append("- Response times within defined thresholds under expected load")
        lines.append("")

        lines.append("## 13. Deployment and Monitoring")
        lines.append("")
        lines.append("- Health check endpoint for readiness/liveness probes")
        lines.append("- Structured logging with correlation IDs for request tracing")
        lines.append("- Metrics collection for operation counts, latencies, and error rates")
        lines.append("- Alerting on error rate thresholds and latency degradation")
        lines.append("- Graceful shutdown with request draining")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by requirement_amplifier v2.0.0 | detail_level={detail_level} | score={score['overall']}/100*")

    return "\n".join(lines)


def execute(requirement: str, detail_level: int = 3, **kwargs) -> SkillResult:
    if not requirement.strip():
        return SkillResult.fail("No requirement provided")

    detail_level = max(1, min(5, detail_level))

    entities = _extract_entities(requirement)
    actions = _extract_actions(requirement)
    constraints = _extract_constraints(requirement)
    roles = _extract_roles(requirement)
    key_phrases = _extract_key_phrases(requirement)

    stories = _generate_user_stories(key_phrases, entities, actions, roles, detail_level)
    implicit_reqs = _infer_implicit_requirements(actions, entities, constraints, roles)
    data_models = _generate_data_models(entities, actions, detail_level)
    nfrs = _generate_nfrs(constraints, detail_level)
    test_scenarios = _generate_test_scenarios(stories, actions, entities, detail_level)
    score = _score_requirement(requirement, entities, actions, constraints, roles)

    markdown = _build_markdown(
        requirement, detail_level, entities, actions, constraints,
        roles, key_phrases, stories, implicit_reqs, data_models,
        nfrs, test_scenarios, score,
    )

    data = {
        "needs_llm": False,
        "detail_level": detail_level,
        "original_requirement": requirement,
        "entities": [e["name"] for e in entities],
        "actions": actions,
        "roles": roles,
        "story_count": len(stories),
        "data_model_count": len(data_models),
        "test_scenario_count": len(test_scenarios),
        "clarity_score": score["overall"],
        "clarity_breakdown": score["breakdown"],
        "clarity_gaps": score["gaps"],
        "implicit_requirements": implicit_reqs,
    }

    return SkillResult.ok(output=markdown, data=data)


def register(registry) -> None:
    registry.register(SkillDef(
        name="requirement_amplifier",
        description="Expand brief requirements into detailed specifications with configurable detail level.",
        category="analysis",
        parameters={
            "type": "object",
            "properties": {
                "requirement": {
                    "type": "string",
                    "description": "Brief requirement to expand",
                },
                "detail_level": {
                    "type": "integer",
                    "description": "Detail level from 1 (basic) to 5 (comprehensive)",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["requirement"],
        },
        handler=execute,
        timeout=30,
    ))
