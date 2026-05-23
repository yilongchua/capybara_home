"""Question taxonomy used by the generator.

The taxonomy lives at ``{vault_root}/00_schema/QUESTION_TAXONOMY.json`` so users
can edit it without touching code. If the file is missing, the default below is
written on first access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAXONOMY_FILENAME = "QUESTION_TAXONOMY.json"


@dataclass(frozen=True)
class Cluster:
    id: int
    name: str
    description: str
    level_1: str
    level_2: str
    level_3: str


DEFAULT_TAXONOMY: list[Cluster] = [
    Cluster(
        id=1,
        name="Definition & Identity",
        description="What the topic actually is and how it is bounded.",
        level_1="What is X?",
        level_2="What kinds / types / categories of X exist?",
        level_3="What distinguishes X from adjacent concepts?",
    ),
    Cluster(
        id=2,
        name="Composition & Structure",
        description="What X is made of and how the parts fit together.",
        level_1="What is X made of? What are its parts or ingredients?",
        level_2="How do the parts relate? What is the structure?",
        level_3="What variations in composition matter?",
    ),
    Cluster(
        id=3,
        name="Process & Method",
        description="How X is made, done, executed, or used.",
        level_1="How do you make / do / use X?",
        level_2="What are the steps and techniques?",
        level_3="Advanced techniques, expert tricks, and common errors.",
    ),
    Cluster(
        id=4,
        name="Origin & History",
        description="Where X came from and how it changed over time.",
        level_1="Where and when did X originate?",
        level_2="How has X evolved?",
        level_3="Turning points, influential figures, lineages.",
    ),
    Cluster(
        id=5,
        name="Geography & Location",
        description="Where X is found, practiced, or experienced.",
        level_1="Where can you find / buy / experience X?",
        level_2="Regional variations.",
        level_3="Notable or expert-recommended locations.",
    ),
    Cluster(
        id=6,
        name="Quality & Evaluation",
        description="How to tell good X from bad X.",
        level_1="How do you tell good X from bad X?",
        level_2="What criteria do experts use?",
        level_3="Edge cases and controversies in evaluation.",
    ),
    Cluster(
        id=7,
        name="Comparison & Contrast",
        description="How X relates to neighbouring options.",
        level_1="X vs Y (common pairings).",
        level_2="When to choose X over Y.",
        level_3="Hybrids and related concepts.",
    ),
    Cluster(
        id=8,
        name="Practical Application",
        description="What X is used for in the real world.",
        level_1="Common use cases or situations.",
        level_2="Lesser-known applications.",
        level_3="Expert / professional use cases.",
    ),
    Cluster(
        id=9,
        name="Risks & Pitfalls",
        description="What can go wrong with X.",
        level_1="Common mistakes and safety concerns.",
        level_2="Limitations and trade-offs.",
        level_3="Edge cases and controversies.",
    ),
    Cluster(
        id=10,
        name="Cultural & Social Context",
        description="How X fits into people's lives and communities.",
        level_1="Cultural significance and etiquette around X.",
        level_2="Community and social aspects.",
        level_3="Modern shifts and debates.",
    ),
    Cluster(
        id=11,
        name="Tools & Resources",
        description="What you need to engage with X.",
        level_1="Essential tools or resources.",
        level_2="Optional or advanced gear.",
        level_3="Brands, suppliers, and communities.",
    ),
    Cluster(
        id=12,
        name="People & Authorities",
        description="Who knows about X and shapes the field.",
        level_1="Notable experts or practitioners.",
        level_2="Communities and organisations.",
        level_3="Schools of thought and lineages.",
    ),
]


def _serialise_default() -> dict[str, Any]:
    return {
        "version": 1,
        "notes": (
            "Each cluster represents one angle a human might ask about a topic. "
            "Levels go from surface (L1) to deep (L3). Edit freely; clusters can be "
            "added or removed, but each must keep an integer id and three level prompts."
        ),
        "clusters": [
            {
                "id": cluster.id,
                "name": cluster.name,
                "description": cluster.description,
                "level_1": cluster.level_1,
                "level_2": cluster.level_2,
                "level_3": cluster.level_3,
            }
            for cluster in DEFAULT_TAXONOMY
        ],
    }


def taxonomy_path(vault_root: Path) -> Path:
    return vault_root / "00_schema" / TAXONOMY_FILENAME


def seed_taxonomy_if_missing(vault_root: Path) -> Path:
    """Write the default taxonomy to the vault if no file exists yet."""
    path = taxonomy_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps(_serialise_default(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return path


def load_taxonomy(vault_root: Path) -> list[Cluster]:
    """Read the user-editable taxonomy from disk, falling back to the default."""
    path = seed_taxonomy_if_missing(vault_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return list(DEFAULT_TAXONOMY)

    raw_clusters = payload.get("clusters") if isinstance(payload, dict) else None
    if not isinstance(raw_clusters, list) or not raw_clusters:
        return list(DEFAULT_TAXONOMY)

    parsed: list[Cluster] = []
    for entry in raw_clusters:
        if not isinstance(entry, dict):
            continue
        try:
            parsed.append(
                Cluster(
                    id=int(entry["id"]),
                    name=str(entry.get("name") or "").strip() or f"Cluster {entry['id']}",
                    description=str(entry.get("description") or "").strip(),
                    level_1=str(entry.get("level_1") or "").strip(),
                    level_2=str(entry.get("level_2") or "").strip(),
                    level_3=str(entry.get("level_3") or "").strip(),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed or list(DEFAULT_TAXONOMY)
