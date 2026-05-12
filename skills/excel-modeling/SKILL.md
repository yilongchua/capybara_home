---
name: excel-modeling
description: Use this skill for formula-heavy Excel modeling tasks such as workbook inspection, formula validation, financial-model color coding, and LibreOffice-based recalculation.
---

# Excel Modeling Skill

## Overview

This skill focuses on advanced XLSX workflows beyond SQL-style analysis. It provides repeatable scripts for workbook inspection, formula validation, financial-model formatting conventions, and deterministic recalculation via LibreOffice.

## When To Use

Use this skill when the user asks to:
- Build or refactor a financial model in Excel
- Validate formulas or detect formula/output errors
- Apply modeling conventions (blue/black/green styles)
- Recalculate a workbook with a spreadsheet engine before delivering

For SQL exploration across Excel/CSV datasets, prefer `data-analysis`.

## Workflow

### Step 1: Inspect workbook structure

```bash
python /mnt/skills/public/excel-modeling/scripts/inspect_workbook.py \
  --input /mnt/user-data/uploads/model.xlsx \
  --output /mnt/user-data/outputs/model-inspection.json
```

### Step 2: Validate formulas and error cells

```bash
python /mnt/skills/public/excel-modeling/scripts/validate_formulas.py \
  --input /mnt/user-data/uploads/model.xlsx \
  --output /mnt/user-data/outputs/model-validation.json
```

### Step 3: Apply financial formatting conventions (optional)

```bash
python /mnt/skills/public/excel-modeling/scripts/apply_financial_formatting.py \
  --input /mnt/user-data/uploads/model.xlsx \
  --output /mnt/user-data/outputs/model-formatted.xlsx
```

### Step 4: Recalculate with LibreOffice (optional but recommended)

```bash
python /mnt/skills/public/excel-modeling/scripts/recalc_libreoffice.py \
  --input /mnt/user-data/outputs/model-formatted.xlsx \
  --output /mnt/user-data/outputs/model-recalculated.xlsx
```

## Script Notes

- `inspect_workbook.py`: summarizes sheets, dimensions, formulas, and typed columns.
- `validate_formulas.py`: reports formula cells and common spreadsheet error values.
- `apply_financial_formatting.py`: applies blue/black/green font conventions:
  - Blue: hardcoded input values
  - Black: formula cells
  - Green: hyperlink/reference cells
- `recalc_libreoffice.py`: runs `soffice --headless` to force spreadsheet-engine recalculation.

## Environment Requirements

System dependency for recalculation:
- LibreOffice (`soffice` in PATH)

Python dependencies used by scripts:
- `openpyxl`

If `soffice` is unavailable, the script exits with an actionable error.
