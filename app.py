import os
import re
import sys
import json
import tempfile
from typing import List, Dict, Any

# Optional heavy deps are avoided; only core libs + PyMuPDF/pdfminer/Pillow/pytesseract

# Text extraction deps (optional fallbacks handled)
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextBoxHorizontal, LTTextLineHorizontal
except Exception:
    extract_pages = None  # type: ignore
    LTTextBoxHorizontal = None  # type: ignore
    LTTextLineHorizontal = None  # type: ignore

try:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore
except Exception:
    pytesseract = None  # type: ignore
    Image = None  # type: ignore

from flask import Flask, request


# -------------------- Extraction (no tables) --------------------

HEADER_FOOTER_MAX_LINES = 4


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"\r\n|\r", "\n", text or "")
    text = re.sub(r"[\t\u00A0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_headers_footers(text: str) -> str:
    lines = [ln for ln in (text or "").split("\n") if ln is not None]
    if len(lines) <= HEADER_FOOTER_MAX_LINES * 2:
        return text
    top = lines[:HEADER_FOOTER_MAX_LINES]
    bottom = lines[-HEADER_FOOTER_MAX_LINES:]

    def is_header_footer_line(ln: str) -> bool:
        return bool(
            re.search(r"^\s*\d+\s*$", ln)
            or re.search(r"\b(page|annual report|confidential|draft)\b", ln, re.I)
            or re.search(r"https?://", ln)
        )

    remove_top = all(is_header_footer_line(ln) or len(ln) <= 2 for ln in top)
    remove_bottom = all(is_header_footer_line(ln) or len(ln) <= 2 for ln in bottom)
    if remove_top:
        lines = lines[HEADER_FOOTER_MAX_LINES:]
    if remove_bottom:
        lines = lines[:-HEADER_FOOTER_MAX_LINES]
    return "\n".join(lines).strip()


def _extract_text_pymupdf(pdf_path: str) -> List[str]:
    assert fitz is not None, "PyMuPDF not available"
    doc = fitz.open(pdf_path)
    pages: List[str] = []
    for page in doc:
        raw = page.get_text("text")
        if (not raw or len((raw or "").strip()) < 20) and pytesseract is not None and Image is not None:
            try:
                pix = page.get_pixmap(dpi=200)
                mode = "RGB" if pix.alpha == 0 else "RGBA"
                img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                ocr_text = pytesseract.image_to_string(img) or ""
                raw = (raw or "").strip() + ("\n" + ocr_text.strip() if ocr_text else "")
            except Exception:
                pass
        cleaned = _strip_headers_footers(_normalize_whitespace(raw or ""))
        pages.append(cleaned)
    return pages


def _extract_text_pdfminer(pdf_path: str) -> List[str]:
    assert extract_pages is not None, "pdfminer.six not available"
    pages: List[str] = []
    for layout in extract_pages(pdf_path):
        chunks: List[str] = []
        for element in layout:
            if isinstance(element, (LTTextBoxHorizontal, LTTextLineHorizontal)):
                chunks.append(element.get_text())
        raw = "".join(chunks)
        cleaned = _strip_headers_footers(_normalize_whitespace(raw))
        pages.append(cleaned)
    return pages


def extract_pages_text(pdf_path: str) -> List[str]:
    assert os.path.isfile(pdf_path), f"File not found: {pdf_path}"
    pages: List[str] = []
    if fitz is not None:
        try:
            pages = _extract_text_pymupdf(pdf_path)
        except Exception:
            pages = []
    if not pages and extract_pages is not None:
        try:
            pages = _extract_text_pdfminer(pdf_path)
        except Exception:
            pages = []
    if not pages:
        raise RuntimeError("Text extraction failed with both PyMuPDF and pdfminer.six")
    return pages


# -------------------- Heuristic summarizer --------------------

SECTION_PATTERNS = {
    "financials": r"revenue|ebit|ebitda|pat|profit|loss|income|balance sheet|cash flow|financial highlight",
    "risks": r"risk|outlook|challenge|headwind|uncertaint",
    "strategy": r"strategy|strategic|priority|roadmap|growth|investment|innovation|market|product|segment",
}


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(0-9)])", text)
    sentences = []
    for s in parts:
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 30:
            sentences.append(s)
    return sentences


def _score_sentence(sentence: str) -> float:
    s = sentence
    score = 0.0
    words = s.split()
    length = len(words)
    if 12 <= length <= 40:
        score += 1.0
    elif length > 8:
        score += 0.5
    numerics = re.findall(r"\b\d[\d,\.]*\b", s)
    score += min(3.0, 0.3 * len(numerics))
    for _, pat in SECTION_PATTERNS.items():
        if re.search(pat, s, re.I):
            score += 0.7
    if re.search(r"yoy|qoq|guidance|margin|dividend|order book|backlog|capex|opex|free cash", s, re.I):
        score += 0.6
    if re.search(r"forward-looking|statutory|notes to accounts|auditor|secretarial", s, re.I):
        score -= 0.8
    return score


def _pick_top_sentences(all_text: str, max_sentences: int = 8) -> List[str]:
    sentences = _split_sentences(all_text)
    seen: set[str] = set()
    unique: List[str] = []
    for s in sentences:
        key = re.sub(r"\W+", " ", s.lower()).strip()
        if key and key not in seen:
            unique.append(s)
            seen.add(key)
    scored = [(s, _score_sentence(s)) for s in unique]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [s for s, _ in scored[:max_sentences]]


def summarize_text(pages: List[str]) -> Dict[str, Any]:
    if not pages:
        return {"summary": "", "key_points": []}
    # Chunk pages by small groups for variety
    chunks: List[str] = []
    size = 3
    for i in range(0, len(pages), size):
        chunks.append("\n\n".join(pages[i : i + size]))

    all_points: List[str] = []
    for chunk in chunks:
        all_points.extend(_pick_top_sentences(chunk, max_sentences=7))

    rescored = [(s, _score_sentence(s)) for s in all_points]
    rescored.sort(key=lambda t: t[1], reverse=True)
    top_points = [s for s, _ in rescored[:12]]

    combined_first = "\n\n".join(chunks[:3]) if chunks else "\n\n".join(pages[:3])
    summary_sentences = _pick_top_sentences(combined_first, max_sentences=8)
    summary = " ".join(summary_sentences)
    return {"summary": summary, "key_points": top_points}


def run(pdf_path: str) -> Dict[str, Any]:
    pages = extract_pages_text(pdf_path)
    res = summarize_text(pages)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    os.makedirs(os.path.join("outputs", "summaries"), exist_ok=True)
    txt_path = os.path.join("outputs", "summaries", f"{stem}.summary.txt")
    json_path = os.path.join("outputs", "summaries", f"{stem}.summary.json")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{stem} — Summary\n")
        f.write("=" * (len(stem) + len(" — Summary")) + "\n\n")
        f.write("Summary\n")
        f.write("-------\n")
        f.write(res["summary"].strip() + "\n\n")
        f.write("Key Points\n")
        f.write("----------\n")
        for i, kp in enumerate(res["key_points"], start=1):
            f.write(f"{i}. {kp}\n")
        f.write("\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"company": stem, **res}, f, ensure_ascii=False, indent=2)
    return {"pdf": pdf_path, "summary_txt": txt_path, "summary_json": json_path, **res}


# -------------------- Minimal Flask UI (single-file, no templates) --------------------

app = Flask(__name__)


def _html_page(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Local PDF Summarizer</title>
<style>
body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 40px; }}
.card {{ max-width: 900px; margin: 0 auto; padding: 24px; border: 1px solid #ddd; border-radius: 12px; }}
button {{ background:#111827; color:#fff; border:0; padding:10px 16px; border-radius:8px; cursor:pointer; }}
pre {{ white-space: pre-wrap; font-family: inherit; }}
</style></head><body>{body}</body></html>"""


@app.get("/")
def index():
    body = (
        "<div class='card'>"
        "<h1>Local PDF Summarizer</h1>"
        "<form action='/summarize' method='post' enctype='multipart/form-data'>"
        "<label>Choose a PDF file</label><br>"
        "<input type='file' name='file' accept='application/pdf' required><br><br>"
        "<button type='submit'>Summarize</button>"
        "</form>"
        "<p style='color:#666;'>Processing is fully local. No data leaves your machine.</p>"
        "</div>"
    )
    return _html_page(body)


@app.post("/summarize")
def summarize():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return _html_page("<div class='card'><p>Please upload a PDF file.</p><a href='/'><button>Go back</button></a></div>")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp)
        tmp_path = tmp.name
    try:
        res = run(tmp_path)
        summary = (res.get("summary") or "").strip()
        key_points = res.get("key_points") or []
        items = "".join([f"<li>{kp}</li>" for kp in key_points])
        body = (
            "<div class='card'>"
            f"<h2>Summary — {file.filename}</h2>"
            f"<pre>{summary}</pre>"
            "<h3>Key Points</h3>"
            f"<ol>{items}</ol>"
            "<a href='/'><button>New PDF</button></a>"
            "</div>"
        )
        return _html_page(body)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    # If a PDF path is provided: run CLI; otherwise start Flask server
    if len(sys.argv) == 2 and os.path.isfile(sys.argv[1]):
        out = run(sys.argv[1])
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        app.run(host="127.0.0.1", port=5000, debug=False)


