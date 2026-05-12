# Deep Code Understanding: Autoresearch + Knowledge Vault

Date: 2026-05-12

## Scope

This folder captures a deep code-level understanding of:
- Autoresearch objective lifecycle
- Knowledge Vault ingestion/compile/search/sufficiency system
- API + UI integration points
- Important files and functions for maintenance and extension

## Documents

- `architecture-map.md`: End-to-end system map and runtime flow.
- `autoresearch-deep-dive.md`: Objective lifecycle, scheduler behavior, command triggers.
- `knowledge-vault-deep-dive.md`: Vault storage model, ingest/compile/lint/sufficiency/search behavior.
- `important-files-and-functions.md`: High-signal index of files and key functions.
- `findings-and-risks.md`: Design strengths, constraints, and technical risks.

## Quick Orientation

1. User trigger enters via chat middleware (`autoresearch` command) or API endpoint.
2. Control plane starts an autoresearch objective and bootstrap run.
3. Pipeline steps execute through `KnowledgeVaultAgent` into `VaultLearningManager`.
4. Results write artifacts + objective progress ledgers.
5. Scheduler keeps daily runs active unless objective reaches endpoint sufficiency.
