"""Dependency declaration files: which files declare dependencies, and what they declare.

One source for the declaration evidence that phantom_import reads and for the
project-context fingerprint that keys its caches. Supported formats:

- pyproject.toml: PEP 621 dependencies and optional-dependencies, Poetry
  dependencies, dev-dependencies and group dependencies;
- setup.py: install_requires and extras_require given as literals or as names
  bound to module-level literals (read with ast, never executed);
- setup.cfg: [options] install_requires and [options.extras_require];
- Pipfile: [packages] and [dev-packages];
- requirements*.txt / requirements*.in and requirements/*.txt;
- environment*.yml / environment*.yaml (conda): dependencies and their pip list.

Each declaration is returned as a requirement string; turning it into import
names is the caller's job.
"""

from __future__ import annotations

import ast
import configparser
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)

_FIXED_NAMES = frozenset({"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"})
_CONDA_SPEC_END = re.compile(r"[=<>!~\s\[]")


def is_declaration_file(name: str) -> bool:
    if name in _FIXED_NAMES:
        return True
    lower = name.lower()
    if lower.startswith("requirements") and lower.endswith((".txt", ".in")):
        return True
    return lower.startswith("environment") and lower.endswith((".yml", ".yaml"))


def declaration_files(directory: Path) -> List[Path]:
    """Declaration files directly in `directory`, in name order."""
    try:
        return sorted(p for p in directory.iterdir() if p.is_file() and is_declaration_file(p.name))
    except OSError:
        return []


def root_declaration_files(root: Path) -> List[Path]:
    """A project root's declaration files, including the requirements/ directory."""
    files = declaration_files(root)
    requirements = root / "requirements"
    if requirements.is_dir():
        files.extend(sorted(requirements.glob("*.txt")))
    return files


def declared_requirements(path: Path) -> List[str]:
    """Requirement strings declared by one file ([] when unreadable or unknown)."""
    # Imported here: project_context reads this module and project_resolution
    # reads project_context.
    from slop_detector.project_resolution import load_toml

    name = path.name.lower()
    try:
        if name == "pyproject.toml":
            return _pyproject_requirements(load_toml(path))
        if name == "pipfile":
            return _pipfile_requirements(load_toml(path))
        if name == "setup.py":
            return _setup_py_requirements(path.read_text(encoding="utf-8", errors="ignore"))
        if name == "setup.cfg":
            return _setup_cfg_requirements(path.read_text(encoding="utf-8", errors="ignore"))
        if name.endswith((".yml", ".yaml")):
            return _conda_requirements(path.read_text(encoding="utf-8", errors="ignore"))
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except (OSError, ValueError, SyntaxError, yaml.YAMLError, configparser.Error) as exc:
        logger.debug("Cannot read declarations from %s: %s", path, exc)
        return []


def _strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


def _table_keys(value: Any) -> List[str]:
    return (
        [str(key) for key in value if str(key).lower() != "python"]
        if isinstance(value, dict)
        else []
    )


def _pyproject_requirements(data: Dict[str, Any]) -> List[str]:
    project = data.get("project", {})
    project = project if isinstance(project, dict) else {}
    found = _strings(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for items in optional.values():
            found.extend(_strings(items))
    tool = data.get("tool", {})
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        found.extend(_table_keys(poetry.get("dependencies")))
        found.extend(_table_keys(poetry.get("dev-dependencies")))
        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for group in groups.values():
                if isinstance(group, dict):
                    found.extend(_table_keys(group.get("dependencies")))
    return found


def _pipfile_requirements(data: Dict[str, Any]) -> List[str]:
    return _table_keys(data.get("packages")) + _table_keys(data.get("dev-packages"))


def _setup_py_requirements(source: str) -> List[str]:
    tree = ast.parse(source)
    bound = _module_bindings(tree)
    found: List[str] = []
    for value in _setup_requirement_values(tree):
        if isinstance(value, ast.Name):
            value = bound.get(value.id, value)
        found.extend(_literal_requirements(value))
    return found


def _module_bindings(tree: ast.Module) -> Dict[str, ast.AST]:
    """Module-level `NAME = <value>` assignments."""
    bound: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bound[target.id] = node.value
    return bound


def _setup_requirement_values(tree: ast.Module) -> List[ast.AST]:
    """The install_requires / extras_require values of every setup() call."""
    return [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_setup_call(node.func)
        for keyword in node.keywords
        if keyword.arg in {"install_requires", "extras_require"}
    ]


def _is_setup_call(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "setup"
    return isinstance(func, ast.Attribute) and func.attr == "setup"


def _literal_requirements(node: ast.AST) -> List[str]:
    try:
        value = ast.literal_eval(node)
    except ValueError:
        return []
    if isinstance(value, dict):
        return [item for items in value.values() for item in _strings(items)]
    return _strings(value)


def _setup_cfg_requirements(text: str) -> List[str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    found: List[str] = []
    if parser.has_option("options", "install_requires"):
        found.extend(parser.get("options", "install_requires").splitlines())
    if parser.has_section("options.extras_require"):
        for _, value in parser.items("options.extras_require"):
            found.extend(value.splitlines())
    return [line for line in found if line.strip()]


def _conda_requirements(text: str) -> List[str]:
    data = yaml.safe_load(text)
    dependencies = data.get("dependencies", []) if isinstance(data, dict) else []
    found: List[str] = []
    for entry in dependencies if isinstance(dependencies, list) else []:
        if isinstance(entry, dict):
            found.extend(_strings(entry.get("pip", [])))
        elif isinstance(entry, str):
            spec = entry.split("::", 1)[-1].strip()
            name = _CONDA_SPEC_END.split(spec, 1)[0]
            if name and name.lower() not in {"python", "pip"}:
                found.append(name)
    return found
