TEMPLATES = {
    "debug": {
        "name": "debug",
        "description": "Debug and fix issues in code",
        "prompt_template": "Debug the following issue in {file_path}: {description}. Error details: {error_details}. Expected behavior: {expected_behavior}.",
        "suggested_engine": "deepseek",
        "max_iterations": 5,
    },
    "refactor": {
        "name": "refactor",
        "description": "Refactor code for better structure and readability",
        "prompt_template": "Refactor the code in {file_path}. Focus on: {focus_areas}. Current issues: {description}. Maintain existing functionality while improving {improvement_targets}.",
        "suggested_engine": "deepseek",
        "max_iterations": 3,
    },
    "test": {
        "name": "test",
        "description": "Generate unit tests for code",
        "prompt_template": "Write comprehensive unit tests for {file_path}. Test framework: {framework}. Coverage targets: {coverage_targets}. Edge cases to consider: {edge_cases}.",
        "suggested_engine": "ollama",
        "max_iterations": 3,
    },
    "document": {
        "name": "document",
        "description": "Generate documentation for code",
        "prompt_template": "Generate documentation for {file_path}. Documentation type: {doc_type}. Target audience: {audience}. Include: {include_sections}.",
        "suggested_engine": "ollama",
        "max_iterations": 2,
    },
    "optimize": {
        "name": "optimize",
        "description": "Optimize code for performance",
        "prompt_template": "Optimize the performance of {file_path}. Current bottleneck: {description}. Performance target: {performance_target}. Constraints: {constraints}.",
        "suggested_engine": "deepseek",
        "max_iterations": 5,
    },
    "migrate": {
        "name": "migrate",
        "description": "Migrate code from one technology to another",
        "prompt_template": "Migrate {file_path} from {source_tech} to {target_tech}. Migration scope: {description}. Compatibility requirements: {compatibility_requirements}.",
        "suggested_engine": "deepseek",
        "max_iterations": 5,
    },
    "review": {
        "name": "review",
        "description": "Review code for quality and best practices",
        "prompt_template": "Review the code in {file_path}. Review focus: {focus_areas}. Coding standards: {standards}. Provide actionable suggestions for: {improvement_targets}.",
        "suggested_engine": "ollama",
        "max_iterations": 2,
    },
}


def get_template(name):
    return TEMPLATES.get(name)


def list_templates():
    return [
        {"name": t["name"], "description": t["description"]}
        for t in TEMPLATES.values()
    ]


def apply_template(name, **kwargs):
    template = TEMPLATES.get(name)
    if template is None:
        raise ValueError(f"Template '{name}' not found")
    return template["prompt_template"].format(**kwargs)
