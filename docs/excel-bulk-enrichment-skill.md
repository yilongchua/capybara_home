# Excel Bulk Enrichment Skill — Future Development Reference

This document captures the full design for a dedicated Equasis / Excel enrichment skill
that was scoped out but deferred in favour of the more general `batch-workflow` skill.
Implement this when you need a turn-key Equasis vessel-data scraper with no additional
LLM configuration.

---

## Overview

A skill that reads an Excel file containing IMO vessel numbers, scrapes Equasis
(equasis.org) for each IMO, and progressively fills in new columns. Designed for
maritime analysts who have a list of vessels and want to enrich it with authoritative
data from the Equasis portal.

---

## SKILL.md Design

### Frontmatter

```yaml
---
name: excel-bulk-enrichment
description: >
  Use this skill when the user uploads an Excel file containing IMO vessel numbers
  (or similar identifiers) and wants to enrich it with external data — for example
  scraping Equasis for ship details (name, flag, type, tonnage, owner, manager,
  class society, P&I club). Handles bulk enrichment with a proof-of-concept
  approval gate before processing all rows. Trigger when user mentions: vessel
  lookup, IMO enrichment, Equasis, ship data, bulk scraping into Excel, or wants
  to "fill in missing columns" from a web source.
workflow: true
---
```

### Workflow Phases

**Phase 0 — Credential Collection**

Before touching the file, call `ask_clarification` with `clarification_type:
"missing_info"` to collect `equasis_username` and `equasis_password`. These are
passed as `--username` / `--password` CLI arguments only — never written to any file.

**Phase 1 — Inspect Excel**

```bash
python /mnt/skills/public/excel-bulk-enrichment/scripts/inspect_excel.py \
  --input /mnt/user-data/uploads/vessels.xlsx
```

Parse the JSON output to confirm:
- Which column holds IMO numbers (by header name or type profile)
- Total data row count
- Whether a prior partial run exists (`last_enriched_row`)

**Phase 2 — POC (rows 2–4)**

Run `batch_update_excel.py` with `--start-row 2 --end-row 4`. The script processes
those 3 rows, updates the workbook, and prints a JSON summary.

**Phase 3 — User Approval Gate**

`ask_clarification` with `clarification_type: "risk_confirmation"` showing:
- Formatted table of 3 POC rows' enriched data
- Total remaining rows
- Estimated time (rows × ~1.5 s)

**Phase 4 — Bulk Processing**

```bash
python /mnt/skills/public/excel-bulk-enrichment/scripts/batch_update_excel.py \
  --input /mnt/user-data/uploads/vessels.xlsx \
  --output /mnt/user-data/outputs/vessels_enriched.xlsx \
  --username <user> --password <pass> \
  --imo-column A \
  --start-row 5 --end-row 580
```

**Phase 5 — Deliver**

`present_files` with the enriched workbook path.

### Script Reference

```
inspect_excel.py --input <path>
  → prints JSON to stdout

batch_update_excel.py
  --input <path>
  --output <path>
  --username <equasis_username>
  --password <equasis_password>
  --imo-column <column_letter_or_name>
  --start-row <int>
  --end-row <int>
  [--delay <float, default 1.5>]
  → prints JSON progress lines; exits 0 on success
```

---

## `scripts/inspect_excel.py`

Modelled after `skills/excel-modeling/scripts/inspect_workbook.py`.

**Args**: `--input` (required), `--output` (optional)

**Output JSON schema:**

```json
{
  "file": "/mnt/user-data/uploads/vessels.xlsx",
  "active_sheet": "Sheet1",
  "data_rows": 580,
  "header_row": ["IMO"],
  "imo_column_candidates": [
    {
      "column_letter": "A",
      "header": "IMO",
      "confidence": "high",
      "sample_values": [9123456, 9234567, 9345678]
    }
  ],
  "enrichment_columns_present": [],
  "last_enriched_row": null,
  "column_profiles": {
    "IMO": {"number": 580, "text": 0, "empty": 0}
  }
}
```

**IMO detection logic**: Column where ≥80% of values are integers in range
1_000_000–9_999_999. `confidence: "high"` when header contains "IMO" AND values
match the range.

**Resume detection**: `last_enriched_row` is the highest row index where at least
one enrichment column is non-empty.

---

## `scripts/scrape_equasis.py`

Single-IMO scraper callable standalone or imported by `batch_update_excel.py`.

**Args**: `--imo`, `--username`, `--password`, `[--session-cookie]`

**Authentication flow**:
1. POST `https://www.equasis.org/EquasisWeb/authen/Login` with form fields
   `j_email` and `j_password`
2. Capture `JSESSIONID` from `Set-Cookie`
3. GET `https://www.equasis.org/EquasisWeb/restricted/ShipInfo?fs=Search&P_IMO=<IMO>`
4. Parse HTML with Python's stdlib `html.parser`

**Output JSON (success)**:

```json
{
  "imo": 9123456,
  "status": "found",
  "ship_name": "EVER GIVEN",
  "ship_type": "Container Ship",
  "flag": "Panama",
  "gross_tonnage": 219079,
  "year_built": 2018,
  "owner": "Shoei Kisen Kaisha Ltd",
  "manager": "Evergreen Marine Corp (Taiwan) Ltd",
  "class_society": "Bureau Veritas",
  "pi_club": "Japan P&I Club",
  "doc_company": "Evergreen Marine Corp (Taiwan) Ltd"
}
```

**Output JSON (no result)**:

```json
{"imo": 9123456, "status": "not_found", "error": "No vessel found"}
```

**Session expiry**: If a mid-batch response redirects to the login page, re-authenticate
once and retry the current row.

---

## `scripts/batch_update_excel.py`

Core batch processor. Loops internally so the LLM only calls it once.

**Args**: `--input`, `--output`, `--username`, `--password`, `--imo-column`,
`--start-row`, `--end-row`, `[--delay default 1.5]`

**Internal loop**:

```python
for row in range(start_row, end_row + 1):
    imo = ws.cell(row=row, column=imo_col_idx).value
    if already_enriched(ws_out, row, enrichment_cols):
        continue  # resume support
    data = scrape_imo(imo, session)   # calls scrape_equasis logic
    write_enrichment(ws_out, row, data, column_map)
    wb_out.save(output_path)           # checkpoint after every row
    print(json.dumps({"row": row, "imo": imo, "status": data["status"]}))
    time.sleep(delay)
```

**Progress output** (per row):

```json
{"type": "row_progress", "row": 2, "imo": 9123456, "status": "found", "ship_name": "EVER GIVEN"}
```

**Final line**:

```json
{"type": "batch_summary", "total_rows": 3, "found": 2, "not_found": 1, "errors": 0}
```

---

## Enrichment Columns Added to Excel

Ten columns appended immediately right of the last existing column:

| Header | Equasis source | Type |
|--------|---------------|------|
| Ship Name | Main heading | text |
| Ship Type | Type field | text |
| Flag | Flag field | text (country name) |
| Gross Tonnage | GT field | integer |
| Year Built | Year Built field | integer |
| Owner | Registered Owner section | text |
| Manager | Technical Manager section | text |
| Class Society | Classification section | text |
| P&I Club | P&I section | text |
| DOC Company | Safety Management section | text |

---

## Dependencies

All already present in `backend/pyproject.toml`:
- `openpyxl>=3.1.3`
- `httpx` (via web_search community tool)
- Python stdlib: `html.parser`, `json`, `time`, `argparse`

No new dependencies needed.

---

## `extensions_config.json` Entry

```json
{
  "skills": {
    "excel-bulk-enrichment": { "enabled": true }
  }
}
```

---

## Verification Steps

1. Create test workbook with 5 rows of known IMO numbers
2. Run `inspect_excel.py` — verify JSON output, `imo_column_candidates` populated
3. Run `batch_update_excel.py` with `--end-row 4` (3 data rows)
4. Verify: enrichment columns created, data populated, `batch_summary` printed
5. Interrupt mid-run, re-run with `--start-row <resume>` — verify already-enriched
   rows are skipped
6. Verify `not_found` IMOs leave enrichment columns blank

---

## Notes

- Skill uses `workflow: true` frontmatter so `LoopDetectionMiddleware` Layer 2
  (frequency-based) is bypassed when this skill is active
- Credentials must never be written to disk or included in any output file
- Container path for scripts: `/mnt/skills/public/excel-bulk-enrichment/scripts/`
