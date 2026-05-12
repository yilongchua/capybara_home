# Financial Modeling Conventions

Use these conventions when editing workbooks for corporate finance workflows.

## Cell Color Semantics

- Blue font: hardcoded user inputs or assumptions
- Black font: formulas and calculated outputs
- Green font: external links or cross-workbook references

## Formula Quality Rules

- Avoid hardcoded constants inside long formulas when a named input cell is clearer.
- Keep formulas consistent across time-series columns/rows.
- Prefer explicit error handling patterns (for example `IFERROR`) when user-facing outputs must never surface raw Excel errors.

## Layout Rules

- Keep one main purpose per sheet (inputs, calculations, outputs).
- Freeze panes for large models and maintain stable headers.
- Use consistent units (for example all amounts in thousands or millions).

## Validation Checklist

- Recalculate workbook before delivery.
- Check for `#DIV/0!`, `#N/A`, `#REF!`, and similar error literals.
- Verify key outputs against known benchmark values where available.
