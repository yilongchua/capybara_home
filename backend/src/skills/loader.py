import os
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill


def get_skills_root_path() -> Path:
    """
    Get the root path of the skills directory.

    Returns:
        Path to the skills directory (CapyHome/skills)
    """
    # backend directory is current file's parent's parent's parent
    backend_dir = Path(__file__).resolve().parent.parent.parent
    # skills directory is sibling to backend directory
    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False) -> list[Skill]:
    """
    Load all skills from the skills directory.

    Scans both public and custom skill directories, parsing SKILL.md files
    to extract metadata. The enabled state is determined by the skills_state_config.json file.

    Args:
        skills_path: Optional custom path to skills directory.
                     If not provided and use_config is True, uses path from config.
                     Otherwise defaults to CapyHome/skills
        use_config: Whether to load skills path from config (default: True)
        enabled_only: If True, only return enabled skills (default: False)

    Returns:
        List of Skill objects, sorted by name
    """
    if skills_path is None:
        if use_config:
            try:
                from src.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                # Fallback to default if config fails
                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    if not skills_path.exists():
        return []

    skills = []

    # Scan skill directories. Skills may live directly in the root (public category)
    # or in a custom/ subdirectory.
    scan_targets: list[tuple[Path, str]] = []

    public_subdir = skills_path / "public"
    if public_subdir.exists() and public_subdir.is_dir():
        # Legacy layout: skills/public/<skill-name>
        scan_targets.append((public_subdir, "public"))
    else:
        # Flat layout: skills/<skill-name> (root is the public category)
        scan_targets.append((skills_path, "public"))

    custom_subdir = skills_path / "custom"
    if custom_subdir.exists() and custom_subdir.is_dir():
        scan_targets.append((custom_subdir, "custom"))

    for category_path, category in scan_targets:
        for current_root, dir_names, file_names in os.walk(category_path):
            # Keep traversal deterministic and skip hidden directories.
            dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
            if "SKILL.md" not in file_names:
                continue

            skill_file = Path(current_root) / "SKILL.md"
            relative_path = skill_file.parent.relative_to(category_path)

            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills.append(skill)

    # Load skills state configuration and update enabled status
    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected in the LangGraph Server when loading skills.
    try:
        from src.config.extensions_config import ExtensionsConfig

        extensions_config = ExtensionsConfig.from_file()
        for skill in skills:
            skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
    except Exception as e:
        # If config loading fails, default to all enabled
        print(f"Warning: Failed to load extensions config: {e}")

    # Filter by enabled status if requested
    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    # Sort by name for consistent ordering
    skills.sort(key=lambda s: s.name)

    return skills
