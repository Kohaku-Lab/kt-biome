---
name: pdf-merge
description: Merge, split, or reorder PDF files. Use when the user mentions combining PDFs, extracting pages, or any "glue these PDFs together" request. Activates automatically in directories containing .pdf files.
license: KohakuTerrarium License 1.0
paths:
  - "*.pdf"
  - "**/*.pdf"
---

# pdf-merge

Use this skill for any operation on PDF files: merging, splitting,
reordering pages, or extracting a subset.

## Decision tree

| Task                              | Tool               |
|-----------------------------------|--------------------|
| Combine 2+ PDFs into one          | `qpdf` or `pdftk`  |
| Extract page ranges               | `qpdf --pages`     |
| Reorder pages                     | `qpdf --pages`     |
| Convert PDF to images / text      | Not this skill —   |
|                                   | use a dedicated    |
|                                   | tool (pdftotext,   |
|                                   | pdfimages).        |

## Merging (preferred: qpdf)

```bash
qpdf --empty --pages in1.pdf in2.pdf in3.pdf -- merged.pdf
```

Fallback when qpdf is not installed:

```bash
pdftk in1.pdf in2.pdf in3.pdf cat output merged.pdf
```

## Verification (required)

Always count pages in the output and sanity-check against the sum of
the inputs:

```bash
qpdf --show-npages merged.pdf
```

Report the page count back to the user. If the numbers don't add up,
flag it — a malformed input PDF silently drops pages in some
concatenation tools.

## Safety

- Never overwrite the original inputs. Write to a new filename.
- If the output file already exists, ask before overwriting.
- Do not `--linearize` unless the user asks for it (changes file
  size noticeably).
