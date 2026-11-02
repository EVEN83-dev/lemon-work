"""
B-003: Skills Registry - registration and lookup of skills.

Ported from standard_mode/core/skills_registry.py, decoupled from Qt.
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import SkillDef, SkillResult

logger = logging.getLogger(__name__)


class SkillsRegistry:
    """
    Bridge-side skills registry — a decoupled mirror of standard_mode/core/skills_registry.py.

    This registry is decoupled from Qt and the standard_mode desktop runtime.
    It provides the same core API (register/unregister/get/list_skills/execute/count)
    as the standard_mode counterpart, but operates independently for the bridge/API path.
    Method signatures should be kept in parity with the standard_mode version.
    """
    def __init__(self):
        self._skills: Dict[str, SkillDef] = {}
        self._project_root: str = ""
        self._hot_watch_dir: Optional[str] = None
        self._file_mtimes: Dict[str, float] = {}
        self._version_history: Dict[str, List[Dict[str, Any]]] = {}
        self._semantic_callback: Optional[Callable] = None
        self._namespaces: Dict[str, str] = {}
        self._deprecated_overrides: Dict[str, SkillDef] = {}
        self._skill_snapshots: Dict[str, List[SkillDef]] = {}
        self._permission_filter: Optional[Callable[[str, str], bool]] = None

    def register(self, skill: SkillDef, namespace: str = "") -> None:
        if skill.name in self._skills:
            old = self._skills[skill.name]
            if skill.name not in self._version_history:
                self._version_history[skill.name] = []
            self._version_history[skill.name].append({
                "version": old.version,
                "timestamp": time.time(),
                "description": old.description,
                "handler_type": type(old.handler).__name__ if old.handler else "none",
                "namespace": self._namespaces.get(skill.name, ""),
            })
            if skill.name not in self._skill_snapshots:
                self._skill_snapshots[skill.name] = []
            import copy
            self._skill_snapshots[skill.name].append(copy.deepcopy(old))
            existing_ns = self._namespaces.get(skill.name, "")
            new_ns = namespace or "bridge"
            if existing_ns and new_ns and existing_ns != new_ns:
                old_has_handler = old.handler is not None and not getattr(old, '_is_placeholder', False)
                new_has_handler = skill.handler is not None and not getattr(skill, '_is_placeholder', False)
                if old_has_handler and not new_has_handler:
                    logger.warning(
                        "Rejecting overwrite of %s (namespace=%s, has_handler) by namespace=%s placeholder",
                        skill.name, existing_ns, new_ns
                    )
                    self._deprecated_overrides[skill.name] = skill
                    return
                logger.info(
                    "Namespace upgrade: %s from %s -> %s", skill.name, existing_ns, new_ns
                )
            logger.warning("Overwriting skill: %s", skill.name)
        self._skills[skill.name] = skill
        if namespace:
            self._namespaces[skill.name] = namespace
        logger.debug("Registered skill: %s (%s) [ns=%s]", skill.name, skill.category, namespace or "bridge")

    def unregister(self, name: str) -> bool:
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def get(self, name: str) -> Optional[SkillDef]:
        return self._skills.get(name)

    def list_skills(self, category: str = "", scenario: str = "") -> List[SkillDef]:
        skills = list(self._skills.values())
        if category:
            skills = [s for s in skills if s.category == category]
        if scenario:
            skills = [s for s in skills if scenario in s.applicable_scenarios]
        return skills

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [s.to_tool_definition() for s in self._skills.values()
                if not s.deprecated and s.handler is not None and self.check_permission(s.name)]

    def execute(self, name: str, args: Dict[str, Any]) -> SkillResult:
        skill = self._skills.get(name)
        if skill is None:
            return SkillResult.fail(f"Skill not found: {name}")
        if skill.handler is None:
            return SkillResult.fail(f"Skill has no handler: {name}")
        if skill.deprecated:
            logger.warning(f"Using deprecated skill: {name} - {skill.deprecation_message}")
        if not self.check_permission(name):
            return SkillResult.fail(f"Permission denied for skill: {name} (level={skill.permission_level})")
        if skill.requires_confirm:
            logger.info(f"Skill {name} requires user confirmation (auto-approved)")
        start = time.time()
        standardized_args = self._normalize_input(name, args)
        try:
            result = skill.handler(**standardized_args)
            if isinstance(result, SkillResult):
                result.duration_ms = (time.time() - start) * 1000
                skill.update_stats(result.duration_ms, result.success)
                return result
            if isinstance(result, str):
                sr = SkillResult.ok(output=result, duration_ms=(time.time() - start) * 1000)
                skill.update_stats(sr.duration_ms, True)
                return sr
            sr = SkillResult.ok(output=str(result), duration_ms=(time.time() - start) * 1000)
            skill.update_stats(sr.duration_ms, True)
            return sr
        except TypeError as e:
            skill.update_stats((time.time() - start) * 1000, False)
            return SkillResult.fail(f"Invalid arguments for {name}: {e}")
        except Exception as e:
            skill.update_stats((time.time() - start) * 1000, False)
            return SkillResult.fail(f"Skill execution error: {e}")

    def _normalize_input(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if "params" in args and isinstance(args["params"], dict):
            merged = dict(args)
            merged.update(args["params"])
            del merged["params"]
            return merged
        return args

    def rollback_skill(self, name: str, version: str = "") -> bool:
        if name not in self._skill_snapshots or not self._skill_snapshots[name]:
            if name not in self._version_history or not self._version_history[name]:
                return False
            logger.info("No snapshot for %s, rollback recorded only", name)
            return False
        snapshots = self._skill_snapshots[name]
        if version:
            target_idx = None
            for i, snap in enumerate(snapshots):
                if getattr(snap, 'version', '') == version:
                    target_idx = i
                    break
            if target_idx is None:
                logger.warning("No snapshot with version %s for %s", version, name)
                return False
            target = snapshots[target_idx]
        else:
            target = snapshots[-1]
        if name in self._skills:
            if name not in self._version_history:
                self._version_history[name] = []
            self._version_history[name].append({
                "version": self._skills[name].version if hasattr(self._skills[name], 'version') else "unknown",
                "timestamp": time.time(),
                "description": "rollback from",
                "restored_from": getattr(target, 'version', 'unknown'),
            })
        import copy
        self._skills[name] = copy.deepcopy(target)
        logger.info("Rolled back skill %s to version %s (real restore)", name, getattr(target, 'version', 'unknown'))
        return True

    def get_version_history(self, name: str) -> List[Dict[str, Any]]:
        return list(self._version_history.get(name, []))

    def set_semantic_callback(self, callback: Callable) -> None:
        self._semantic_callback = callback

    def set_permission_filter(self, filter_fn: Callable[[str, str], bool]) -> None:
        self._permission_filter = filter_fn

    def check_permission(self, skill_name: str, permission_level: str = "") -> bool:
        if self._permission_filter is None:
            return True
        skill = self._skills.get(skill_name)
        if skill is None:
            return False
        plevel = permission_level or skill.permission_level
        return self._permission_filter(skill_name, plevel)

    def count(self) -> int:
        return len(self._skills)

    def set_project_root(self, root: str) -> None:
        self._project_root = root

    def get_project_root(self) -> str:
        return self._project_root

    def is_high_risk(self, name: str) -> bool:
        skill = self._skills.get(name)
        if skill is None:
            return False
        return skill.risk_level in ("high", "critical") or skill.requires_confirm

    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        tools = []
        for skill in self._skills.values():
            if skill.deprecated or skill.handler is None:
                continue
            tool_def = skill.to_tool_definition()
            tool_def["_risk"] = "high" if self.is_high_risk(skill.name) else "low"
            tool_def["_category"] = skill.category
            tools.append(tool_def)
        return tools

    def get_categories(self) -> List[str]:
        cats = set()
        for skill in self._skills.values():
            cats.add(skill.category)
        return sorted(cats)

    def auto_discover(self, package_path: Optional[str] = None) -> int:
        if package_path is None:
            package_path = os.path.dirname(__file__)
        self._hot_watch_dir = package_path
        count = 0
        for importer, modname, ispkg in pkgutil.iter_modules([package_path]):
            if modname.startswith("_") or modname in ("models", "registry", "router"):
                continue
            try:
                module = importlib.import_module(f".{modname}", package="bridge.skills")
                register_fn = getattr(module, "register", None)
                if register_fn and callable(register_fn):
                    register_fn(self)
                    count += 1
                    logger.info(f"Auto-discovered skill module: {modname}")
                mod_file = getattr(module, "__file__", "")
                if mod_file:
                    self._file_mtimes[mod_file] = os.path.getmtime(mod_file)
            except Exception as e:
                logger.warning(f"Failed to load skill module {modname}: {e}")
        self._discover_declarations(package_path)
        self._register_business_skills()
        return count

    def _discover_declarations(self, package_path: str) -> int:
        decl_dir = os.path.join(package_path, "declarations")
        if not os.path.isdir(decl_dir):
            return 0
        from .models import parse_skill_md
        count = 0
        for fname in os.listdir(decl_dir):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(decl_dir, fname)
            decl = parse_skill_md(filepath)
            if decl is None:
                continue
            errors = decl.validate()
            if errors:
                logger.warning("SKILL.md validation errors in %s: %s", fname, errors)
            skill_name = decl.name
            if skill_name in self._skills:
                existing = self._skills[skill_name]
                existing.applicable_scenarios = decl.applicable_scenarios or existing.applicable_scenarios
                existing.examples = decl.examples or existing.examples
                existing.metadata.tags = decl.tags or existing.metadata.tags
                existing.metadata.dependencies = decl.dependencies or existing.metadata.dependencies
                existing.input_schema = {"inputs": decl.inputs} if decl.inputs else existing.input_schema
                existing.output_schema = {"outputs": decl.outputs} if decl.outputs else existing.output_schema
                if decl.capabilities:
                    existing.applicable_scenarios = list(set(existing.applicable_scenarios + decl.capabilities))
                if decl.namespace:
                    self._namespaces[skill_name] = decl.namespace
                logger.info("Enriched skill %s from SKILL.md declaration", skill_name)
            else:
                handler = self._find_handler_for_declaration(skill_name, package_path)
                skill_def = decl.to_skill_def(handler=handler)
                self._skills[skill_name] = skill_def
                if decl.namespace:
                    self._namespaces[skill_name] = decl.namespace
                if handler:
                    logger.info("Registered skill %s from SKILL.md (handler from module)", skill_name)
                else:
                    logger.info("Registered skill %s from SKILL.md (no handler)", skill_name)
            count += 1
        return count

    def _find_handler_for_declaration(self, decl_name: str, package_path: str) -> Optional[Callable]:
        try:
            module = importlib.import_module("." + decl_name, package="bridge.skills")
        except Exception:
            return None
        for attr_name in ("execute", "_handler"):
            obj = getattr(module, attr_name, None)
            if obj and callable(obj):
                return obj
        for attr_name in dir(module):
            if attr_name.startswith("_handler") or attr_name.endswith("_handler"):
                obj = getattr(module, attr_name, None)
                if obj and callable(obj):
                    return obj
        primary_name = decl_name.replace("_skill", "").replace("_", "")
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name, None)
            if not obj or not callable(obj):
                continue
            if type(obj).__name__ == 'function' and attr_name[0].islower():
                attr_normalized = attr_name.replace("_", "")
                if primary_name in attr_normalized or attr_normalized in primary_name:
                    return obj
        return None

    def _register_business_skills(self) -> int:
        try:
            from shared.skills.business_skills import BUSINESS_SKILLS
            count = 0
            for skill in BUSINESS_SKILLS:
                try:
                    self.register(skill, namespace="business")
                    count += 1
                except Exception as e:
                    logger.warning("Failed to register business skill %s: %s", skill.name, e)
            logger.info("Registered %d business skills with namespace=business", count)
            return count
        except ImportError as e:
            logger.info("Business skills not available: %s", e)
            return 0
        except Exception as e:
            logger.warning("Business skills registration failed: %s", e)
            return 0

    def check_hot_reload(self) -> int:
        if not self._hot_watch_dir:
            return 0
        reloaded = 0
        for importer, modname, ispkg in pkgutil.iter_modules([self._hot_watch_dir]):
            if modname.startswith("_") or modname in ("models", "registry", "router"):
                continue
            try:
                module = importlib.import_module(f".{modname}", package="bridge.skills")
                mod_file = getattr(module, "__file__", "")
                if mod_file and os.path.exists(mod_file):
                    current_mtime = os.path.getmtime(mod_file)
                    prev_mtime = self._file_mtimes.get(mod_file, 0)
                    if current_mtime > prev_mtime:
                        importlib.reload(module)
                        self._file_mtimes[mod_file] = current_mtime
                        register_fn = getattr(module, "register", None)
                        if register_fn and callable(register_fn):
                            register_fn(self)
                        reloaded += 1
                        logger.info("Hot-reloaded skill module: %s", modname)
            except Exception as e:
                logger.warning("Failed to hot-reload skill module %s: %s", modname, e)
        decl_reloaded = self._check_declaration_reload()
        reloaded += decl_reloaded
        return reloaded

    def _check_declaration_reload(self) -> int:
        if not self._hot_watch_dir:
            return 0
        decl_dir = os.path.join(self._hot_watch_dir, "declarations")
        if not os.path.isdir(decl_dir):
            return 0
        reloaded = 0
        for fname in os.listdir(decl_dir):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(decl_dir, fname)
            try:
                current_mtime = os.path.getmtime(filepath)
                prev_mtime = self._file_mtimes.get(filepath, 0)
                if current_mtime <= prev_mtime:
                    continue
                self._file_mtimes[filepath] = current_mtime
                from .models import parse_skill_md
                decl = parse_skill_md(filepath)
                if decl is None:
                    continue
                errors = decl.validate()
                if errors:
                    logger.warning("SKILL.md hot-reload validation errors in %s: %s", fname, errors)
                    continue
                skill_name = decl.name
                if skill_name in self._skills:
                    existing = self._skills[skill_name]
                    existing.description = decl.description or existing.description
                    existing.category = decl.category or existing.category
                    existing.applicable_scenarios = decl.applicable_scenarios or existing.applicable_scenarios
                    existing.examples = decl.examples or existing.examples
                    existing.metadata.tags = decl.tags or existing.metadata.tags
                    existing.metadata.dependencies = decl.dependencies or existing.metadata.dependencies
                    if decl.capabilities:
                        existing.applicable_scenarios = list(set(existing.applicable_scenarios + decl.capabilities))
                    logger.info("Hot-reloaded SKILL.md for %s", skill_name)
                else:
                    handler = self._find_handler_for_declaration(skill_name, self._hot_watch_dir)
                    skill_def = decl.to_skill_def(handler=handler)
                    self._skills[skill_name] = skill_def
                    logger.info("Hot-loaded new SKILL.md for %s", skill_name)
                reloaded += 1
            except Exception as e:
                logger.warning("Failed to hot-reload SKILL.md %s: %s", fname, e)
        return reloaded

    def find_by_intent(self, user_input: str, top_k: int = 3,
                       min_confidence: float = 0.1) -> List[Tuple[str, float]]:
        query_lower = user_input.lower()
        query_words = set(query_lower.split())
        scored: List[Tuple[str, float]] = []
        for name, skill in self._skills.items():
            score = 0.0
            name_words = name.replace("_", " ").lower().split()
            name_overlap = sum(1 for w in name_words if w in query_lower)
            score += name_overlap * 2.0
            desc_words = skill.description.lower().split()
            desc_overlap = sum(1 for w in desc_words if w in query_lower)
            score += desc_overlap * 1.0
            for tag in skill.applicable_scenarios:
                if tag.lower() in query_lower:
                    score += 1.5
            for keyword in skill.metadata.tags:
                if keyword.lower() in query_lower:
                    score += 1.0
                kw_words = set(keyword.lower().replace("_", " ").split())
                overlap = len(query_words & kw_words)
                if overlap > 0:
                    score += overlap * 0.8
            if skill.category.lower() in query_lower:
                score += 0.5
            if skill.deprecated:
                score *= 0.1
            if score > 0:
                scored.append((name, score))
        if self._semantic_callback is not None:
            try:
                semantic_scores = self._semantic_callback(user_input, list(self._skills.keys()))
                if isinstance(semantic_scores, dict):
                    for skill_name, sem_score in semantic_scores.items():
                        if skill_name in self._skills:
                            for i, (sn, ss) in enumerate(scored):
                                if sn == skill_name:
                                    scored[i] = (sn, ss + sem_score * 5.0)
                                    break
                            else:
                                if sem_score > 0.3:
                                    scored.append((skill_name, sem_score * 5.0))
            except Exception:
                pass
        if not scored:
            return []
        max_score = max(s for _, s in scored)
        if max_score > 0:
            normalized = [(name, round(score / max_score, 4)) for name, score in scored]
        else:
            normalized = scored
        filtered = [(name, conf) for name, conf in normalized if conf >= min_confidence]
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[:top_k]

    def clear(self) -> None:
        self._skills.clear()

    def get_skill_catalog(self) -> List[Dict[str, Any]]:
        catalog: List[Dict[str, Any]] = []
        for name, skill in self._skills.items():
            catalog.append({
                "name": name,
                "description": skill.description,
                "category": skill.category,
                "riskLevel": skill.risk_level,
                "version": skill.metadata.version,
                "tags": skill.metadata.tags,
                "usageCount": skill.metadata.usage_count,
                "successRate": skill.metadata.success_rate,
                "examples": skill.examples,
                "permissionLevel": skill.permission_level,
                "applicableScenarios": skill.applicable_scenarios,
                "fallbackSkill": skill.fallback_skill,
                "chainSkills": skill.chain_skills,
            })
        return sorted(catalog, key=lambda x: x["category"])

    def get_skill_stats(self) -> Dict[str, Any]:
        total = len(self._skills)
        by_category: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}
        total_usage = 0
        for skill in self._skills.values():
            cat = skill.category
            by_category[cat] = by_category.get(cat, 0) + 1
            risk = skill.risk_level
            by_risk[risk] = by_risk.get(risk, 0) + 1
            total_usage += skill.metadata.usage_count
        return {
            "total_skills": total,
            "by_category": by_category,
            "by_risk_level": by_risk,
            "total_usage_count": total_usage,
        }


_registry: Optional[SkillsRegistry] = None


class _SkillReloadHandler:
    def __init__(self, registry: SkillsRegistry):
        self._registry = registry

    def on_modified(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".py"):
            return
        modname = os.path.splitext(os.path.basename(event.src_path))[0]
        if modname.startswith("_") or modname in ("models", "registry", "router"):
            return
        try:
            module = importlib.import_module(f".{modname}", package="bridge.skills")
            importlib.reload(module)
            register_fn = getattr(module, "register", None)
            if register_fn and callable(register_fn):
                register_fn(self._registry)
            logger.info(f"Watchdog hot-reloaded: {modname}")
        except Exception as e:
            logger.warning(f"Watchdog reload failed for {modname}: {e}")

    def on_created(self, event):
        self.on_modified(event)


BATCH_READ_FILES_DEF = {
    "name": "batch_read_files",
    "description": "批量读取多个文件，返回每个文件的内容摘要。用于高效分析项目结构，避免逐文件串行读取。",
    "parameters": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要读取的文件路径列表（最多 20 个）",
            },
            "max_chars_per_file": {
                "type": "integer",
                "description": "每个文件最大读取字符数",
                "default": 3000,
            },
        },
        "required": ["files"],
    },
}

SCAN_PROJECT_DEF = {
    "name": "scan_project",
    "description": "扫描项目结构，返回目录树、关键文件列表、技术栈识别结果。用于在深入分析前快速了解项目全貌。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "项目根目录路径",
            },
            "max_depth": {
                "type": "integer",
                "description": "目录扫描最大深度",
                "default": 3,
            },
        },
        "required": ["path"],
    },
}

QUICK_ANALYZE_DEF = {
    "name": "quick_analyze",
    "description": "快速分析指定路径下的项目结构。自动识别项目类型、技术栈、入口文件，并返回关键信息摘要。比逐个读取文件更高效。",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "项目根目录路径",
            },
            "focus": {
                "type": "string",
                "enum": ["structure", "code", "config", "full"],
                "description": "分析重点：structure(结构)/code(代码)/config(配置)/full(全面)",
                "default": "structure",
            },
        },
        "required": ["path"],
    },
}


def batch_read_files_handler(args: dict) -> dict:
    files = args.get("files", [])
    max_chars = args.get("max_chars_per_file", 3000)
    if not files:
        return {
            "success": False,
            "error": "files 列表为空",
            "summary": "读取失败: 文件列表为空",
            "message": "未提供任何文件路径",
        }
    if len(files) > 20:
        files = files[:20]

    results: Dict[str, Any] = {}
    success_count = 0
    errors: List[str] = []
    allowed_ext = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css',
                   '.json', '.md', '.txt', '.yaml', '.yml', '.toml',
                   '.cfg', '.ini', '.xml', '.svg', '.sh', '.bat'}

    for fpath in files:
        try:
            if not os.path.exists(fpath):
                errors.append(f"{fpath}: 文件不存在")
                continue
            if not os.path.isfile(fpath):
                errors.append(f"{fpath}: 不是文件")
                continue
            ext = os.path.splitext(fpath)[1].lower()
            if ext not in allowed_ext:
                errors.append(f"{fpath}: 不支持的文件类型 {ext}")
                continue
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(max_chars)
            lines = content.split('\n')
            preview = '\n'.join(lines[:10])
            results[fpath] = {
                "lines": len(lines),
                "preview": preview,
                "size": len(content),
            }
            success_count += 1
        except Exception as e:
            errors.append(f"{fpath}: {str(e)}")

    summary_text = f"成功读取 {success_count}/{len(files)} 个文件"
    if success_count == 0 and errors:
        summary_text += "。错误: " + "; ".join(errors[:3])
    return {
        "success": success_count > 0,
        "files_read": success_count,
        "files_total": len(files),
        "results": results,
        "errors": errors if errors else None,
        "summary": summary_text,
        "message": summary_text,
    }


def scan_project_handler(args: dict) -> dict:
    path = args.get("path", ".")
    max_depth = args.get("max_depth", 3)
    if not os.path.exists(path):
        return {
            "success": False,
            "error": f"路径不存在: {path}",
            "summary": f"扫描失败: 路径不存在 ({path})",
            "message": "路径不存在，无法扫描项目结构",
        }
    if not os.path.isdir(path):
        return {
            "success": False,
            "error": f"不是目录: {path}",
            "summary": f"扫描失败: {path} 不是目录",
            "message": "目标路径不是目录，无法扫描",
        }

    key_files = {
        'README.md': False, 'README': False, 'package.json': False,
        'requirements.txt': False, 'pyproject.toml': False, 'setup.py': False,
        'Cargo.toml': False, 'go.mod': False, 'pom.xml': False,
        'Makefile': False, 'Dockerfile': False, '.gitignore': False,
    }
    ext_to_stack: Dict[str, str] = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.tsx': 'typescript', '.jsx': 'javascript', '.java': 'java',
        '.go': 'go', '.rs': 'rust', '.cpp': 'cpp', '.h': 'cpp',
        '.html': 'html', '.css': 'css', '.scss': 'css',
    }
    tech_stack: Dict[str, bool] = {v: False for v in set(ext_to_stack.values())}
    tree: List[str] = []
    total_files = 0
    total_dirs = 0
    file_types: Dict[str, int] = {}
    ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                   '.idea', '.vscode', 'dist', 'build', 'egg-info'}

    for root_dir, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        depth = root_dir.replace(path, '').count(os.sep)
        if depth >= max_depth:
            dirs[:] = []
            continue
        indent = '  ' * depth
        dir_name = os.path.basename(root_dir) or path
        tree.append(f"{indent}{dir_name}/")
        total_dirs += 1
        for file in files:
            total_files += 1
            ext = os.path.splitext(file)[1].lower()
            if ext:
                file_types[ext] = file_types.get(ext, 0) + 1
            if file in key_files:
                key_files[file] = True
                tree.append(f"{indent}  {file} *")
            elif depth < 2:
                tree.append(f"{indent}  {file}")
            stack = ext_to_stack.get(ext)
            if stack:
                tech_stack[stack] = True

    primary_stack = [s for s, found in tech_stack.items() if found]
    common_entries = ['main.py', 'app.py', 'index.js', 'index.ts', 'main.go',
                      'Main.java', 'App.tsx', 'App.jsx', 'server.py', 'manage.py']
    entry_files: List[str] = []
    for root_dir, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            if f in common_entries:
                rel = os.path.relpath(os.path.join(root_dir, f), path)
                entry_files.append(rel)

    return {
        "success": True,
        "path": os.path.abspath(path),
        "total_files": total_files,
        "total_dirs": total_dirs,
        "file_types": dict(sorted(file_types.items(), key=lambda x: -x[1])[:15]),
        "primary_stack": primary_stack,
        "key_files_found": [k for k, v in key_files.items() if v],
        "entry_files": entry_files[:5],
        "directory_tree": tree[:80],
        "summary": (
            f"项目 {os.path.basename(path)}: "
            f"{total_files} 个文件, {total_dirs} 个目录, "
            f"主技术栈: {', '.join(primary_stack) or '未知'}"
        ),
    }


def quick_analyze_handler(args: dict) -> dict:
    path = args.get("path", ".")
    focus = args.get("focus", "structure")

    scan_result = scan_project_handler({"path": path, "max_depth": 3})
    if not scan_result.get("success"):
        return scan_result

    key_files_to_read: List[str] = []
    for kf in ['README.md', 'package.json', 'requirements.txt', 'pyproject.toml',
               'setup.py', 'Cargo.toml', 'go.mod', 'Makefile']:
        full_path = os.path.join(path, kf)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            key_files_to_read.append(full_path)

    for entry in scan_result.get("entry_files", [])[:2]:
        full_path = os.path.join(path, entry)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            key_files_to_read.append(full_path)

    read_result = None
    if key_files_to_read:
        read_result = batch_read_files_handler({
            "files": key_files_to_read[:10],
            "max_chars_per_file": 5000,
        })

    analysis: Dict[str, Any] = {
        "project_name": os.path.basename(os.path.abspath(path)),
        "structure": scan_result,
        "key_files": read_result,
    }

    summary_parts = [f"## 项目分析: {analysis['project_name']}"]
    summary_parts.append(f"\n### 基本信息")
    summary_parts.append(f"- 总文件数: {scan_result['total_files']}")
    summary_parts.append(f"- 总目录数: {scan_result['total_dirs']}")
    summary_parts.append(f"- 主技术栈: {', '.join(scan_result['primary_stack']) or '未知'}")

    if scan_result.get('key_files_found'):
        summary_parts.append(f"\n### 配置文件")
        summary_parts.append(f"- 已找到: {', '.join(scan_result['key_files_found'])}")

    if scan_result.get('entry_files'):
        summary_parts.append(f"\n### 入口文件")
        for ef in scan_result['entry_files']:
            summary_parts.append(f"- {ef}")

    if scan_result.get('file_types'):
        summary_parts.append(f"\n### 文件类型分布")
        for ext, count in list(scan_result['file_types'].items())[:8]:
            summary_parts.append(f"- {ext}: {count} 个文件")

    if focus in ('code', 'full') and read_result and read_result.get('results'):
        summary_parts.append(f"\n### 关键文件预览")
        for fpath, info in read_result['results'].items():
            summary_parts.append(f"\n**{os.path.basename(fpath)}** ({info['lines']} 行)")
            summary_parts.append("```")
            summary_parts.append(info['preview'][:500])
            summary_parts.append("```")

    return {
        "success": True,
        "analysis": analysis,
        "summary": '\n'.join(summary_parts),
        "total_steps": 3,
        "message": "快速分析完成",
    }


BUILTIN_BATCH_HANDLERS: Dict[str, Callable] = {
    "batch_read_files": batch_read_files_handler,
    "scan_project": scan_project_handler,
    "quick_analyze": quick_analyze_handler,
}


def get_skills_registry() -> SkillsRegistry:
    global _registry
    if _registry is None:
        _registry = SkillsRegistry()
    return _registry
