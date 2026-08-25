# DrugsRus Invoice Processing Pipeline - Setup & Testing Guide

## 📋 System Overview

This is a sophisticated invoice processing pipeline with three main components:

### 1. **Invoice Extraction Pipeline**
- **Endpoint**: `POST /extract-invoice`
- **Flow**:
  - Upload a PDF invoice file
  - Extract text using `pdfplumber`
  - Validate extracted text quality
  - If text is meaningful → Process with OpenAI GPT
  - If text is garbled/image-based → Use Llama Parse OCR → Process with GPT
  - Hybrid mode: Merge textual + OCR results when both are needed

**Output**: Structured invoice data (company details, line items, totals)

### 2. **Supplier Product Matching**
- **Endpoint**: `POST /match-supplier`
- **Algorithm**: RapidFuzz + Sentence Transformers semantic similarity
- **Input**: Actual product name + list of candidate products
- **Output**: Top 50 matches sorted by similarity score

### 3. **Country-Aware Product Matching**
- **Endpoint**: `POST /match-products`
- **Enhancement**: Considers invoice country and supplier countries
- **Prioritizes**: Products from same country/region as supplier
- **Output**: Top 50 matches with country metadata

---

## 🚀 Quick Start

### Prerequisites
```bash
# Python 3.10+
python --version

# Virtual environment already set up at .venv/
```

### 1. Verify `.env` Configuration
```bash
# Check that .env has valid API keys
cat .env
```

Your `.env` should contain:
```
OPEN_API_KEY = "sk-proj-..."
OPENAI_MODEL = "gpt-4" or "gpt-4o"
LLAMA_API_KEY_1 = "llx-..."
LLAMA_API_KEY_2 = "llx-..."
```

### 2. Start the Server
```bash
# Navigate to project directory
cd C:\Users\saubhagya.singh\Desktop\DrugsRus-Invoice-Processing_main

# Run uvicorn
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     Application startup complete
```

### 3. Test the API

**Option A: Using Swagger UI (Interactive)**
```
http://localhost:8001/docs
```

**Option B: Using Postman**
- Import the provided `DrugsRus_Invoice_API.json` collection
- Test endpoints with pre-configured examples

**Option C: Using curl**
```bash
# Test invoice extraction
curl -X POST http://localhost:8001/extract-invoice \
  -F "file=@path/to/invoice.pdf"

# Test supplier matching
curl -X POST http://localhost:8001/match-supplier \
  -H "Content-Type: application/json" \
  -d '{
    "actual": "Ibuprofen 400mg",
    "candidates": ["Ibuprofen 400mg tablet", "Aspirin 500mg"]
  }'
```

---

## 🔌 API Endpoints

### POST /extract-invoice
**Purpose**: Extract structured data from an invoice PDF

**Request**:
```
Content-Type: multipart/form-data
Body: file (PDF binary)
```

**Response** (200 OK):
```json
{
  "Invoice": {
    "company_name": "ABC Pharmaceuticals",
    "invoice_number": "INV-2024-001",
    "invoice_date": "2024-01-15",
    "total_amount": "5000.00",
    "currency": "EUR",
    "payment_terms": "Net 30",
    ...
  },
  "InvoiceProducts": [
    {
      "product_name": "Paracetamol 500mg",
      "quantity": 100,
      "unit_price": "2.50",
      "total": "250.00"
    },
    ...
  ]
}
```

**Response** (503 Service Unavailable):
```json
{
  "success": false,
  "message": "OpenAI quota exceeded or too many requests.",
  "error": "..."
}
```

---

### POST /match-supplier
**Purpose**: Find similar products using text similarity

**Request**:
```json
{
  "actual": "Aspirin 500mg Tablets",
  "candidates": [
    "Aspirin 500 mg tablet",
    "Ibuprofen 400mg",
    "Paracetamol 1000mg",
    "Aspirin tablets 500mg"
  ]
}
```

**Response** (200 OK):
```json
{
  "actual": "Aspirin 500mg Tablets",
  "matches": [
    {
      "product": "Aspirin 500 mg tablet",
      "score": 0.95
    },
    {
      "product": "Aspirin tablets 500mg",
      "score": 0.92
    },
    {
      "product": "Ibuprofen 400mg",
      "score": 0.45
    }
  ]
}
```

---

### POST /match-products
**Purpose**: Find similar products with country/region awareness

**Request**:
```json
{
  "actual": "Aspirin 500mg",
  "actualRecord": {
    "invoiceCountry": {
      "countryId": 1,
      "countryCode": "DE",
      "countryName": "Germany"
    },
    "supplierCountries": [
      {
        "countryId": 1,
        "countryCode": "DE",
        "countryName": "Germany"
      },
      {
        "countryId": 2,
        "countryCode": "AT",
        "countryName": "Austria"
      }
    ]
  },
  "candidateRecords": [
    {
      "product": "Aspirin 500mg tablet",
      "countryId": 1,
      "countryCode": "DE",
      "countryName": "Germany"
    },
    {
      "product": "Aspirin 500mg",
      "countryId": 3,
      "countryCode": "FR",
      "countryName": "France"
    }
  ]
}
```

**Response** (200 OK):
```json
{
  "actual": {
    "product": "Aspirin 500mg",
    "countryId": 1,
    "countryCode": "DE",
    "countryName": "Germany"
  },
  "matches": [
    {
      "product": "Aspirin 500mg tablet",
      "countryId": 1,
      "countryCode": "DE",
      "countryName": "Germany",
      "score": 0.95
    }
  ]
}
```

---

## 📊 Pipeline Flow Diagram

```
PDF Upload
    ↓
Extract Text (pdfplumber)
    ↓
Text Quality Check
    ├─→ Meaningful? → Process with OpenAI GPT ✓
    └─→ Poor quality? → Llama Parse OCR → Process with OpenAI GPT ✓
    ↓
Parse LLM Response
    ↓
Check for Missing Fields/Products
    ├─→ Complete? → Return Result ✓
    └─→ Incomplete? → Run OCR + GPT → Merge Results ✓
    ↓
Return Structured Invoice
```

---

## 🧪 Testing Examples

### Test 1: Simple Product Matching
```bash
curl -X POST http://localhost:8001/match-supplier \
  -H "Content-Type: application/json" \
  -d '{
    "actual": "Ibuprofen 200mg",
    "candidates": [
      "Ibuprofen 200 mg tablet",
      "Ibuprofen 400mg",
      "Paracetamol 500mg"
    ]
  }'
```

### Test 2: Country-Aware Matching
```bash
curl -X POST http://localhost:8001/match-products \
  -H "Content-Type: application/json" \
  -d '{
    "actual": "Paracetamol",
    "actualRecord": {
      "invoiceCountry": {"countryId": 1, "countryCode": "DE", "countryName": "Germany"},
      "supplierCountries": [{"countryId": 1, "countryCode": "DE", "countryName": "Germany"}]
    },
    "candidateRecords": [
      {"product": "Paracetamol 500mg", "countryId": 1, "countryCode": "DE", "countryName": "Germany"},
      {"product": "Paracetamol 1000mg", "countryId": 3, "countryCode": "FR", "countryName": "France"}
    ]
  }'
```

---

## 📁 Project Structure

```
DrugsRus-Invoice-Processing_main/
├── app.py                      # FastAPI application & endpoints
├── invoice_processing.py       # Invoice extraction logic
├── llama_ocr_processing.py    # Llama Parse OCR integration
├── similarity_search_updated.py # Product matching algorithms
├── prompts.py                  # LLM prompts for extraction
├── share_convert.py            # XML/Markdown conversion utilities
├── requirements.txt            # Python dependencies
├── .env                        # API keys (DO NOT COMMIT)
├── .env.example                # Template for .env
├── DrugsRus_Invoice_API.json  # Postman collection
├── logs/                       # Application logs
│   └── pipeline.log           # Detailed request/response logs
└── .venv/                     # Virtual environment
```

---

## 📝 Logging

Logs are stored in `logs/pipeline.log` with rotation (5MB max per file, 5 backups kept).

**Log Levels**:
- `DEBUG`: Detailed extraction steps, data structures
- `INFO`: API requests, key events, extraction results
- `WARNING`: Noisy loggers (suppressed: httpx, openai, urllib3)

**View recent logs**:
```bash
tail -50 logs/pipeline.log
```

---

## 🔑 Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPEN_API_KEY` | OpenAI API key | `sk-proj-...` |
| `OPENAI_MODEL` | GPT model version | `gpt-4` or `gpt-4o` |
| `LLAMA_API_KEY_1` | Llama Parse primary key | `llx-...` |
| `LLAMA_API_KEY_2` | Llama Parse secondary key | `llx-...` |

---

## 🐛 Troubleshooting

### Error: `ModuleNotFoundError: No module named 'share_convert'`
**Solution**: Ensure you're running from the project root directory.

### Error: `KeyError: 'LLAMA_API_KEY_1'`
**Solution**: Create a `.env` file with valid API keys (see `.env.example`)

### Error: `OpenAI quota exceeded`
**Response**: API returns 503 with error message. Check your OpenAI account quota.

### Error: `Connection refused on port 8001`
**Solution**: Ensure the server is running: `uvicorn app:app --host 0.0.0.0 --port 8001`

---

## 🚀 Production Deployment

For production deployment:
```bash
# Use production server (not --reload)
uvicorn app:app --host 0.0.0.0 --port 8001 --workers 4

# Or with Gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:8001
```

---

## 📚 Related Files

- **Postman Collection**: `DrugsRus_Invoice_API.json` - Import into Postman for local testing
- **API Documentation**: http://localhost:8001/docs (Swagger UI)
- **Alternative Docs**: http://localhost:8001/redoc (ReDoc)
