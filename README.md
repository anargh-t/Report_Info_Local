## Local PDF Summarizer (single-file, no APIs)

Summarize any PDF locally on your machine using a single Python file (`app.py`). Use CLI or a small built-in Flask website. No external API calls; everything runs offline. Extraction uses PyMuPDF/pdfminer with optional Tesseract OCR; summarization is extractive and heuristic.

### Features
- **Local only**: No API keys, no network calls.
- **Robust text extraction**: PyMuPDF → pdfminer.six fallback; optional OCR via Tesseract for image‑only pages.
- **Table extraction (optional)**: Camelot/Tabula still available; can be disabled.
- **Heuristic summarization**: Extractive scoring with finance‑aware signals; returns a concise summary + key points.
- **Structured outputs**: TXT and JSON (with `summary` + `key_points`).

## How it works
1) Extract per‑page text via PyMuPDF (fallback pdfminer), with OCR for image‑only pages.
2) Rank sentences using simple finance‑aware scoring; assemble concise summary and key points.
3) Write outputs to TXT and JSON under `outputs/summaries/`.

Key modules:
- `src/extractor.py`: text/OCR/table extraction, logging to `outputs/logs/`.
- `src/summarizer.py`: chunking, LLM calls, heuristic summarizer, section categorization.
- `src/summarizer.py`: orchestrates extract → summarize → write outputs (via `run`).
- `config.py`: centralized configuration, environment overrides.

## Installation
- Python 3.10+
- Install dependencies:
```bash
pip install -r requirements.txt
```
- Optional (for better results on Windows):
  - **Tesseract OCR** and add to PATH, e.g. `C:\\Program Files\\Tesseract-OCR`.
  - **Ghostscript** for Camelot lattice mode.
  - **Java Runtime** for Tabula.

### Environment setup
- Python 3.10+
- Optional: Tesseract OCR for image‑only PDFs (Windows path typically `C:\\Program Files\\Tesseract-OCR`).

## Quick Start
- Install deps:
```powershell
pip install -r requirements.txt
```
- Run end‑to‑end on a single PDF (CLI):
```powershell
python app.py data\syntheticdata.pdf
```
- Or use the Flask website (upload + view in browser):
```powershell
python app.py
```
Open `http://127.0.0.1:5000/` and upload a PDF.

- Flask website (upload + view in browser):
```powershell
pip install -r requirements.txt
python app_flask.py
```
Open `http://127.0.0.1:5000/` and upload a PDF. Results render as a page with the summary and key points.

## Outputs
Written under `outputs/`:
- `summaries/`:
  - `<stem>.summary.txt` — plain text summary and numbered key points.
  - `<stem>.summary.json` — `{ company, summary, key_points }`.

## Configuration
Edit `config.py` or override via environment variables. Key settings:
- **Extraction** (`config.extraction`):
  - `TABLE_TOOL` = `camelot` | `tabula` | `auto`
  - `chunk_pages_min`, `chunk_pages_max` (chunking size)
  - `remove_headers_footers` (heuristic cleanup)
- **Pipeline** (`config.pipeline`):
  - `OUTPUT_DIR`, `TEXTS_DIR`, `TABLES_DIR`, `LOGS_DIR`, `SUMMARIES_DIR`

## Notes and Tips
- No API keys needed. Offline by default.
- If table extraction is slow on Windows, set `TABLE_TOOL=tabula` or disable Java/Camelot.
- OCR is used per‑page only when extracted text is minimal (install Tesseract to enable).

### Sharing the project
- No secrets required.

