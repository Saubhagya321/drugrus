# DrugsRus Invoice Processing

FastAPI service that extracts structured data from supplier invoice PDFs (via LlamaParse OCR + OpenAI GPT-4o) and matches extracted products/suppliers against a candidate list using hybrid text similarity.

## Prerequisites

- Python 3.12 (tested on 3.12.13)
- An OpenAI API key
- A LlamaParse (LlamaCloud) API key

## Setup

Run these from the project root (the folder you unzipped, containing `app.py`).

### Windows (PowerShell / Git Bash)

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Configure environment variables

Copy the example env file and fill in your real API keys:

```bash
cp .env.example .env
```

Then open `.env` and replace the placeholder values:

```
OPEN_API_KEY = "sk-proj-YOUR-OPENAI-API-KEY-HERE"
OPENAI_MODEL = "gpt-4o"
COUNTER_MODEL = "gpt-4o-mini"
LLAMA_API_KEY_1 = "llx-YOUR-LLAMA-API-KEY-1-HERE"
LLAMA_API_KEY_2 = "llx-YOUR-LLAMA-API-KEY-2-HERE"
DEBUG_FILE_MODE = "false"
```

- `OPEN_API_KEY` — your OpenAI API key.
- `OPENAI_MODEL` — model used for full invoice extraction (default `gpt-4o`).
- `COUNTER_MODEL` — cheaper model used just to count how many invoices are in a single PDF (default `gpt-4o-mini`).
- `LLAMA_API_KEY_1` / `LLAMA_API_KEY_2` — LlamaParse OCR keys. Two keys are supported so the app can fall back to the second key if the first hits a rate limit.
- `DEBUG_FILE_MODE` — set to `"true"` to dump extra per-match debug files (scoring breakdowns) during supplier/product matching; leave `"false"` for normal use.

## Run the server

With the virtual environment activated:

```bash
python app.py
```

The API will start on `http://0.0.0.0:8001` (equivalently `http://localhost:8001`).

Interactive API docs (Swagger UI) are available at:

```
http://localhost:8001/docs
```

## Available endpoints

### `POST /extract-invoice`
Upload an invoice PDF and get back structured JSON (invoice details + line items).

```bash
curl -X POST http://localhost:8001/extract-invoice \
  -F "file=@/path/to/invoice.pdf"
```

### `POST /match-supplier`
Plain text-similarity ranking of candidate product/supplier names against an actual value — no country logic.

```bash
curl -X POST http://localhost:8001/match-supplier \
  -H "Content-Type: application/json" \
  -d '{
    "actual": "Hyzaar 50mg + 12,5mg/28 coated tabl.(2x14)",
    "candidates": [
      "HYZAAR 100MG/25MG X 28 TABS",
      "HYZAAR 50MG/12.5MG X 28 TABS"
    ]
  }'
```

### `POST /match-products`
Country-aware product matching: candidates from the invoice's own country are ranked first, then candidates from any of the supplier's known countries, then everything else — similarity score breaks ties within each group.

```bash
curl -X POST http://localhost:8001/match-products \
  -H "Content-Type: application/json" \
  -d '{
    "actual": "Hyzaar 50mg + 12,5mg/28 coated tabl.(2x14)",
    "candidates": [],
    "actualRecord": {
      "product": "Hyzaar 50mg + 12,5mg/28 coated tabl.(2x14)",
      "invoiceCountry": {"countryId": 14, "countryCode": "CZ", "countryName": "Czech Republic"},
      "supplierCountries": [
        {"countryId": 14, "countryCode": "CZ", "countryName": "Czech Republic"},
        {"countryId": 58, "countryCode": "PL", "countryName": "Poland"}
      ]
    },
    "candidateRecords": [
      {"product": "HYZAAR 50MG/12.5MG X 28 TABS", "supplierProductDescription": "HYZAAR 50MG/12.5MG X 28 TABS", "countryId": 58, "countryCode": "PL", "countryName": "Poland"}
    ]
  }'
```

## Project layout

```
app.py                      FastAPI app / route definitions
invoice_processing.py       OCR -> LLM extraction pipeline orchestration
llama_ocr_processing.py     LlamaParse OCR integration
prompts.py                  LLM prompt templates and extraction rules
similarity_search_updated.py Supplier/product text-similarity matching
middleware/post_process.py  Post-processing (e.g. dropping empty invoice entries)
api_run/                    Per-request intermediate extraction artifacts (auto-created)
logs/                       Rotating application logs (auto-created)
```

## Notes

- The first run will download a sentence-transformers embedding model (`all-MiniLM-L6-v2`) used for similarity matching; this requires an internet connection the first time and is cached locally afterward.
- `api_run/` and `logs/` are created automatically on first use and are gitignored — safe to delete between runs if you want a clean slate.
