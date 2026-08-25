# Code Changes Summary

Complete summary of all changes made to the DrugsRus Invoice Processing pipeline in this session.

---

## 📋 Overview

Two major enhancements were implemented:

1. **Intermediate Result Storage** — Save each pipeline step's output to `api_run/` for debugging
2. **Multi-Invoice Support** — Detect and extract multiple invoices from a single PDF using a 2-LLM pipeline

---

## 🗂️ Files Modified

| File | Type of Change |
|------|---------------|
| `app.py` | Modified — pass filename to extractor |
| `invoice_processing.py` | Modified — new functions + multi-invoice flow |
| `prompts.py` | Modified — added counter prompt + dynamic prompt builder |
| `SETUP_GUIDE.md` | **NEW** — full setup guide |
| `API_RUN_DEBUG.md` | **NEW** — intermediate result documentation |
| `MARKDOWN_VIEWING_GUIDE.md` | **NEW** — how to view OCR markdown |
| `DrugsRus_Invoice_API.json` | **NEW** — Postman collection for local testing |
| `codechanges.md` | **NEW** — this file |

---

## 1️⃣ Intermediate Result Storage

### Purpose
Every API call now saves each step's output to `api_run/<filename>_<timestamp>/` for debugging and audit.

### New Directory Structure
```
api_run/
└── invoice_20260825_121324/
    ├── 01_raw_text_extraction.json     ← Text from pdfplumber
    ├── 02_invoice_count_textual.json   ← Count detected
    ├── 03_llm_response_textual.json    ← LLM extraction response
    ├── 04_llama_ocr_markdown_fallback.json
    ├── 04_llama_ocr_markdown_fallback.md   ← Raw markdown (also saved)
    ├── 05_invoice_count_ocr_fallback.json
    ├── 06_llm_response_ocr_fallback.json
    ├── 07_final_result.json            ← Final response
    └── metadata.json                    ← Run metadata
```

### New Functions in `invoice_processing.py`

```python
API_RUN_DIR = Path(__file__).resolve().parent / "api_run"
API_RUN_DIR.mkdir(exist_ok=True)

def create_run_directory(filename: str) -> Path:
    """Create a directory for this API run with timestamp and filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = Path(filename).stem
    run_dir = API_RUN_DIR / f"{file_stem}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

def save_intermediate_result(run_dir: Path, step_num: int, step_name: str, data) -> None:
    """Save intermediate result as JSON, and as .md if it's OCR output."""
    # Saves .json always
    # Also saves .md when step_name contains "ocr" and data is string

def save_metadata(run_dir: Path, filename: str, extraction_method: str, success: bool) -> None:
    """Save metadata about the run to metadata.json"""
```

### `app.py` Change

```python
# Before
result = extract_full_invoice_structure(file_like)

# After
result = extract_full_invoice_structure(file_like, filename=file.filename)
```

---

## 2️⃣ Multi-Invoice Support

### Purpose
A single PDF may contain multiple invoices. Previously, the system only extracted one (or merged them). Now it detects the count and returns all invoices as an array.

### Architecture: 2-LLM Pipeline

```
PDF → Text/OCR Extraction
        ↓
    ┌───────────────────────────────┐
    │ Call 1: Counter LLM (cheap)   │
    │ Model: gpt-4o-mini            │
    │ Returns: { "count": N }       │
    └───────────────────────────────┘
        ↓
    ┌───────────────────────────────┐
    │ Build Dynamic Prompt          │
    │ - Existing rules (unchanged)  │
    │ - Small "N invoices" addition │
    │ - Schema with N objects       │
    │ - Each has 'index' field      │
    └───────────────────────────────┘
        ↓
    ┌───────────────────────────────┐
    │ Call 2: Extractor LLM         │
    │ Model: existing OPENAI_MODEL  │
    │ Returns: N invoice objects    │
    └───────────────────────────────┘
```

### New Response Format

**Before:**
```json
{
  "Invoice": { "invoiceNo": "...", ... },
  "InvoiceProducts": [ ... ]
}
```

**After:**
```json
{
  "count": 2,
  "Invoices": [
    {
      "index": 0,
      "Invoice": { "invoiceNo": "9301597438", ... },
      "InvoiceProducts": [ ... ]
    },
    {
      "index": 1,
      "Invoice": { "invoiceNo": "9301600209", ... },
      "InvoiceProducts": [ ... ]
    }
  ]
}
```

---

### Changes in `prompts.py`

Added two things at the end of the file:

#### A. Counter Prompt
```python
COUNT_INVOICES_PROMPT = """
Analyze the following document and count the number of DISTINCT invoices present.

Detection indicators (a new invoice usually starts when you see):
- A new invoice/receipt number (e.g., Belegnummer, Invoice No, Rechnungsnummer, Factura)
- A new invoice date paired with a new invoice number
- Repeated header blocks (company logo/address followed by invoice metadata)
- Explicit separators or repeating "# RECHNUNG"/"# INVOICE" headers
- A total/summary block followed by another header block

Rules:
- Return the total number of distinct invoices found.
- If it clearly is a single invoice, return count = 1.
- Multiple pages of the SAME invoice count as 1 invoice.

Return ONLY a JSON object in this exact format:
{{"count": <integer>}}

Document:
{text}
"""
```

#### B. Dynamic Prompt Builder
```python
def build_multi_invoice_prompt(count: int) -> str:
    """
    Build a dynamic invoice extraction prompt for `count` invoices.
    Reuses INVOICE_EXTRACTION_RULES; wraps INVOICE_SCHEMA in an Invoices array
    with an `index` field per invoice.
    """
    # Builds an Invoices array with `count` objects, each with index 0..N-1
    # Preserves existing INVOICE_EXTRACTION_RULES unchanged
    # Adds a small "IMPORTANT (Multi-Invoice Extraction)" section
    # Returns a prompt template string with {text} placeholder
```

The dynamic schema built looks like:
```json
{
  "Invoices": [
    {
      "index": 0,
      "Invoice": { ...same fields as INVOICE_SCHEMA... },
      "InvoiceProducts": [ ... ]
    },
    {
      "index": 1,
      "Invoice": { ... },
      "InvoiceProducts": [ ... ]
    }
    // ... N objects
  ]
}
```

---

### Changes in `invoice_processing.py`

#### A. Imports Updated
```python
# Before
from prompts import TEXT_INVOICE_PROMPT

# After
from prompts import TEXT_INVOICE_PROMPT, COUNT_INVOICES_PROMPT, build_multi_invoice_prompt
```

#### B. New Constant
```python
COUNTER_MODEL = os.environ.get('COUNTER_MODEL', 'gpt-4o-mini')
```

#### C. New Function: `count_invoices()`
```python
def count_invoices(text: str) -> int:
    """Detect invoice count using cheap LLM. Fallback to 1 on failure."""
    try:
        prompt = PromptTemplate.from_template(COUNT_INVOICES_PROMPT)
        llm = ChatOpenAI(model=COUNTER_MODEL, temperature=0, api_key=OPEN_API_KEY)\
            .bind(response_format={"type": "json_object"})
        parser = JsonOutputParser()
        chain = prompt | llm | parser
        result = chain.invoke({"text": text})
        count = int(result.get("count", 1))
        return count if count >= 1 else 1
    except Exception:
        return 1  # Fallback to single invoice
```

#### D. New Function: `process_invoice_data_with_llm_multi()`
```python
def process_invoice_data_with_llm_multi(text: str, count: int):
    """Extract `count` invoices in ONE LLM call using dynamic schema."""
    dynamic_prompt = build_multi_invoice_prompt(count)
    prompt = PromptTemplate.from_template(dynamic_prompt)
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=OPEN_API_KEY)\
        .bind(response_format={"type": "json_object"})
    parser = JsonOutputParser()
    chain = prompt | llm | parser
    # ... standard error handling for OpenAI errors ...
    return chain.invoke({"text": text})
```

#### E. New Helper: `_needs_ocr_fallback()`
```python
def _needs_ocr_fallback(invoices: list) -> bool:
    """Return True if any invoice is empty or missing fields/products."""
    if not invoices:
        return True
    for inv in invoices:
        invoice_info = inv.get("Invoice", {}) or {}
        products = inv.get("InvoiceProducts", []) or []
        all_empty = all(v in [None, ""] for v in invoice_info.values())
        missing_fields = [k for k, v in invoice_info.items() if v in [None, ""]]
        if all_empty or missing_fields or not products:
            return True
    return False
```

#### F. Refactored: `extract_full_invoice_structure()`

**Textual Path (main flow):**
```python
# 1. Extract text from PDF
# 2. Save raw text
# 3. If text not meaningful → OCR path (below)
# 4. Count invoices (Call 1)
count = count_invoices(text)

# 5. Extract all N invoices (Call 2)
result = process_invoice_data_with_llm_multi(text, count)

# 6. If any invoice empty/incomplete → OCR fallback
if _needs_ocr_fallback(result.get("Invoices", [])):
    llama_extraction = extract_ocr_data(file_like)
    ocr_count = count_invoices(llama_extraction)
    result = process_invoice_data_with_llm_multi(llama_extraction, ocr_count)

# 7. Return with count
result["count"] = count
return result
```

**OCR-Only Path (when text is unreadable):**
```python
llama_extraction = extract_ocr_data(file_like)
ocr_count = count_invoices(llama_extraction)
result = process_invoice_data_with_llm_multi(llama_extraction, ocr_count)
result["count"] = ocr_count
return result
```

**Removed:** The per-field merge logic (line-by-line merging of textual + OCR fields) — replaced with a simpler "use OCR entirely if textual incomplete" strategy since it maps cleanly to multi-invoice.

---

## 3️⃣ Environment Variables

Add to `.env` (optional — has default):
```env
COUNTER_MODEL = "gpt-4o-mini"
```

Full `.env` requirements:
```env
OPEN_API_KEY = "sk-proj-..."
OPENAI_MODEL = "gpt-4" or "gpt-4o"
COUNTER_MODEL = "gpt-4o-mini"       ← NEW (optional, defaults to gpt-4o-mini)
LLAMA_API_KEY_1 = "llx-..."
LLAMA_API_KEY_2 = "llx-..."
```

---

## 4️⃣ Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Cheap model for counter** (`gpt-4o-mini`) | Small task, doesn't need full model power |
| **Two LLM call types** (not N calls) | 1 counter + 1 extractor = predictable cost |
| **Existing extraction prompt untouched** | Only appends small "N invoices" instruction |
| **Dynamic schema built in Python** | Guarantees LLM sees N slots to fill |
| **0-based index field** | Programmer-friendly, matches array indexing |
| **Fallback to N=1** on counter failure | Preserves existing behavior for edge cases |
| **Simplified OCR fallback** (use entirely, no merge) | Per-field merge was complex + assumed single invoice |
| **Full text to counter** (not truncated) | Cheap model handles it, avoids missing late invoices |

---

## 5️⃣ Testing

### Start Server
```bash
.venv\Scripts\activate
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

### Postman
Import `DrugsRus_Invoice_API.json` and hit:
- `POST http://localhost:8001/extract-invoice` (upload PDF)

### Verify Multi-Invoice
Upload a PDF with multiple invoices (e.g., the Herba Chemosan document with 2 invoices).

Expected response:
```json
{
  "count": 2,
  "Invoices": [
    { "index": 0, "Invoice": {"invoiceNo": "9301597438", ...}, "InvoiceProducts": [...] },
    { "index": 1, "Invoice": {"invoiceNo": "9301600209", ...}, "InvoiceProducts": [...] }
  ]
}
```

### Debug via `api_run/`
Check the folder for each step's intermediate output.

---

## 6️⃣ API Endpoints (Unchanged Interface)

All 3 endpoints keep the same HTTP interface — only `POST /extract-invoice` response format changed to multi-invoice.

| Endpoint | Method | Change |
|----------|--------|--------|
| `/extract-invoice` | POST | Response format now `{count, Invoices[]}` |
| `/match-supplier` | POST | No changes |
| `/match-products` | POST | No changes |

---

## 7️⃣ Backward Compatibility

⚠️ **Breaking change on `/extract-invoice`**: Clients expecting `{Invoice, InvoiceProducts}` will need to update to consume `{count, Invoices: [...]}`. Even for single invoices, the response is now wrapped in the array with `index: 0`.

---

## 📚 Related Documentation Files

- `SETUP_GUIDE.md` — Complete project setup & API docs
- `API_RUN_DEBUG.md` — How to debug via `api_run/` folder
- `MARKDOWN_VIEWING_GUIDE.md` — Viewing OCR markdown files
- `DrugsRus_Invoice_API.json` — Postman collection

---

## 🎯 Summary of Total Changes

- **3 files modified**: `app.py`, `invoice_processing.py`, `prompts.py`
- **5 new files added**: 4 docs + 1 Postman collection
- **~180 lines added** (functions + prompts + docs)
- **~100 lines removed** (obsolete per-field merge logic)
- **1 new env var** (optional): `COUNTER_MODEL`
- **1 new folder auto-created**: `api_run/`
