---
name: pdf-pro
description: Use this skill for advanced PDF workflows including extraction, OCR, merge/split operations, and fillable-form processing.
---

# PDF Pro Skill

## Overview

This skill provides practical PDF processing workflows that go beyond plain text reading. It includes scripts for text/table extraction, OCR of scanned PDFs, merge/split operations, and filling AcroForm fields.

## When To Use

Use this skill when the user asks to:
- Extract structured content from PDFs (text and table-like rows)
- OCR scanned/image PDFs
- Merge or split PDF files
- Fill fillable PDF form fields

## Workflow

### Step 1: Extract text and lightweight table data

```bash
python /mnt/skills/public/pdf-pro/scripts/extract_text_tables.py \
  --input /mnt/user-data/uploads/document.pdf \
  --output /mnt/user-data/outputs/document-extract.json
```

### Step 2: OCR scanned PDFs (if needed)

```bash
python /mnt/skills/public/pdf-pro/scripts/ocr_pdf.py \
  --input /mnt/user-data/uploads/scanned.pdf \
  --output /mnt/user-data/outputs/scanned-ocr.md
```

### Step 3: Merge or split PDFs

```bash
# Merge
python /mnt/skills/public/pdf-pro/scripts/merge_split_pdf.py \
  --mode merge \
  --inputs /mnt/user-data/uploads/a.pdf /mnt/user-data/uploads/b.pdf \
  --output /mnt/user-data/outputs/merged.pdf

# Split pages 1-3
python /mnt/skills/public/pdf-pro/scripts/merge_split_pdf.py \
  --mode split \
  --input /mnt/user-data/uploads/long.pdf \
  --start-page 1 \
  --end-page 3 \
  --output /mnt/user-data/outputs/split.pdf
```

### Step 4: Fill AcroForm fields

```bash
python /mnt/skills/public/pdf-pro/scripts/fill_forms.py \
  --input /mnt/user-data/uploads/form.pdf \
  --field-values /mnt/skills/public/pdf-pro/assets/form-field-values.example.json \
  --output /mnt/user-data/outputs/form-filled.pdf
```

## Environment Requirements

System dependencies for OCR path:
- `tesseract`
- `pdftoppm` (from poppler-utils)

Python dependencies used by scripts:
- `pypdf`
- `pdfplumber`
- `pytesseract`

If OCR system dependencies are missing, `ocr_pdf.py` exits with an actionable error.
