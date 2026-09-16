# Repository Guidelines

## Project Structure & Module Organization

This repository is a compact architecture and integration-evidence workspace. Root-level Markdown files contain plans and procedures: `REFINED_MVP1_WORK_PLAN.md` defines delivery workstreams, while `SIG_MCP_CONNECTION_TEST.md` documents the MCP verification workflow. Files named `sig-mcp-*.json` are captured machine-readable evidence. The dated `.docx` file is a versioned architecture deliverable. Root-level `.eml` files preserve source correspondence and may contain sensitive headers. There is currently no application source tree, dependency manifest, asset directory, or automated test suite; do not describe referenced parent-workspace paths as if they exist in this checkout.

## Build, Test, and Development Commands

No build step is required. Before submitting changes, run focused document checks from the repository root:

```powershell
rg --files
rg -n '^#{1,6} ' -g '*.md' .
Get-Content -Raw .\sig-mcp-live-capture.json | ConvertFrom-Json | Out-Null
python -m zipfile -t .\2026-09-15_GRP-ARC-001_MVP1_Solution_Architecture_Specification_v2.2.docx
```

These commands inventory tracked artifacts, review heading structure, parse JSON, and verify that the Word package is not corrupt. Repeat the JSON check for every edited capture. Also open changed `.docx` files in Word or LibreOffice to inspect pagination, tables, and diagrams.

## Coding Style & Naming Conventions

Use UTF-8, ATX headings, sentence-case section titles, short paragraphs, and blank lines around lists and fenced blocks. Add a language tag to code fences. Keep JSON at two-space indentation and preserve captured field names and timestamps. Follow existing naming patterns: uppercase underscore-separated names for major Markdown deliverables, lowercase kebab-case for evidence captures, and `YYYY-MM-DD_<document-id>_<title>_vN.N.docx` for controlled documents. Prefer relative Markdown links.

## Testing Guidelines

Treat validation as evidence review: confirm JSON parses, internal links resolve, dates and receipt IDs agree across artifacts, and procedural commands remain reproducible. No coverage target applies. Never hand-edit captured results to make a run appear successful; document limitations alongside the evidence.

## Commit & Pull Request Guidelines

This checkout contains no `.git` history, so an established commit convention cannot be inferred. Use concise, imperative, scoped subjects such as `docs: clarify MCP validation limits`. Pull requests should explain the purpose, list changed artifacts, report validation performed, and link the relevant decision or issue. Include screenshots only when a `.docx` layout change needs visual review.

## Security & Configuration

Do not commit OAuth tokens, provider keys, cookies, or unredacted session data. Review captures for credentials and personal data before committing; retain endpoint and protocol metadata only when it is intentionally part of the evidence record.
