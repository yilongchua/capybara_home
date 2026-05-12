# PDF Quality Checks

Use this checklist after any PDF transformation.

## Content Integrity

- Ensure page count matches expectation.
- Ensure no pages are dropped, duplicated, or reordered unexpectedly.
- Verify text extraction contains required sections.

## OCR Quality

- Spot-check at least two pages for OCR accuracy.
- Confirm numbers, dates, and proper nouns are preserved correctly.
- If OCR quality is poor, increase rendering DPI or use source-specific preprocessing.

## Form Filling

- Confirm each required field was populated.
- Confirm the output opens correctly in standard PDF viewers.
- Preserve original form layout and avoid clipping text.

## Merge/Split Operations

- Confirm page ranges are accurate.
- Confirm bookmarks/metadata requirements with the user if needed.
- Confirm output filename communicates operation result clearly.
