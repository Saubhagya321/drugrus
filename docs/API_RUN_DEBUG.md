# API Run Debug & Intermediate Results

## 📊 Overview

Every time you extract an invoice via the `/extract-invoice` endpoint, intermediate results are automatically saved to the `api_run/` folder. This allows you to debug and monitor each step of the extraction pipeline.

---

## 📁 Folder Structure

```
api_run/
├── invoice_20240825_114530/
│   ├── 01_raw_text_extraction.json
│   ├── 02_llama_ocr_markdown.json
│   ├── 03_llm_response.json
│   ├── 04_final_merged_result.json
│   └── metadata.json
├── report_20240825_120015/
│   ├── 01_raw_text_extraction.json
│   ├── 02_llm_response_textual.json
│   └── metadata.json
└── ...
```

---

## 🔄 Extraction Workflows & Output Files

### Workflow 1: Textual-Only Extraction
**When**: PDF has clear, readable text
**Files Generated**:
```
01_raw_text_extraction.json     ← Extracted text from PDF
02_llm_response_textual.json    ← LLM parsed invoice data
03_final_result_textual_only.json ← Final output (no changes)
metadata.json                    ← Extraction metadata
```

### Workflow 2: OCR-Only Extraction
**When**: PDF has images or unreadable text
**Files Generated**:
```
01_raw_text_extraction.json     ← Raw extracted text (poor quality)
02_llama_ocr_markdown.json      ← Llama Parse OCR markdown output
03_llm_response_ocr.json        ← LLM parsed OCR data
metadata.json                    ← Extraction metadata
```

### Workflow 3: Hybrid Extraction (Textual + OCR)
**When**: Textual extraction is incomplete (missing fields/products)
**Files Generated**:
```
01_raw_text_extraction.json       ← Extracted text from PDF
02_llm_response_textual.json      ← LLM parsed textual data (incomplete)
03_llama_ocr_markdown_hybrid.json ← Llama Parse OCR markdown
04_llm_response_ocr_hybrid.json   ← LLM parsed OCR data
05_final_merged_result.json       ← Final merged output
metadata.json                      ← Extraction metadata
```

---

## 📄 File Descriptions

### 01_raw_text_extraction.json
**Content**: Text extracted directly from PDF using `pdfplumber`

```json
{
  "content": "Company Name\nInvoice Number: INV-2024-001\nDate: 2024-01-15\n..."
}
```

**Purpose**: Verify if PDF text is readable or if OCR fallback is needed

---

### 02_llama_ocr_markdown.json
**Content**: Markdown output from Llama Parse OCR service

```json
{
  "content": "# COMPANY DETAILS\n\n**Company Name**: ABC Pharma\n\n# INVOICE\n\n| Product | Qty | Price |\n|---------|-----|-------|\n| Aspirin | 100 | $2.50 |..."
}
```

**Purpose**: See what Llama Parse extracted from the PDF (especially for image-based invoices)

---

### 03_llm_response_*.json
**Content**: LLM (OpenAI GPT) parsed structured data

```json
{
  "Invoice": {
    "company_name": "ABC Pharmaceuticals",
    "invoice_number": "INV-2024-001",
    "invoice_date": "2024-01-15",
    "total_amount": "5000.00",
    "currency": "EUR"
  },
  "InvoiceProducts": [
    {
      "product_name": "Paracetamol 500mg",
      "quantity": 100,
      "unit_price": "2.50",
      "total": "250.00"
    }
  ]
}
```

**Purpose**: See how LLM interpreted the text

---

### 05_final_merged_result.json
**Content**: Final merged result (textual + OCR combined)

```json
{
  "Invoice": {
    "company_name": "ABC Pharmaceuticals",
    "invoice_number": "INV-2024-001",
    "delivery_date": "2024-01-20",  ← From OCR fallback
    "total_amount": "5000.00"
  },
  "InvoiceProducts": [
    {
      "product_name": "Paracetamol 500mg",
      "quantity": 100,
      "unit_price": "2.50",
      "total": "250.00"
    }
  ]
}
```

**Purpose**: Final output with missing fields filled from OCR

---

### metadata.json
**Content**: Metadata about the extraction run

```json
{
  "timestamp": "2024-08-25T11:45:30.123456",
  "input_file": "invoice.pdf",
  "extraction_method": "hybrid",
  "success": true,
  "output_dir": "C:\\...\\api_run\\invoice_20240825_114530"
}
```

**Purpose**: Track which extraction method was used and success status

---

## 🔍 How to Use for Debugging

### Scenario 1: Invoice not extracting correctly
1. Look at `01_raw_text_extraction.json` - Is text readable?
2. If yes, check `02_llm_response_textual.json` - Is LLM parsing correct?
3. If no, check `02_llama_ocr_markdown.json` - Did OCR capture it properly?

### Scenario 2: Missing fields in final result
1. Check `02_llm_response_textual.json` - Were fields extracted from text?
2. Check `04_llm_response_ocr_hybrid.json` - Did OCR find the missing fields?
3. Check `05_final_merged_result.json` - Were fields merged correctly?

### Scenario 3: Slow extraction
1. Check `metadata.json` extraction_method - Hybrid extraction is slower
2. Check extraction times in `logs/pipeline.log`

---

## 🧹 Cleanup

To clean up old runs:

```bash
# Remove all runs older than 7 days
forfiles /S /D +7 /P "api_run" /C "cmd /c IF @isdir==TRUE rmdir /S /Q @path"

# Or manually delete specific runs
rm -r api_run/invoice_20240825_*
```

---

## 🔧 Configuration

To disable intermediate result saving (for production):
Edit `invoice_processing.py` and comment out the `save_intermediate_result()` calls.

To change output directory:
Edit this line in `invoice_processing.py`:
```python
API_RUN_DIR = Path(__file__).resolve().parent / "api_run"
```

---

## 📊 Example: Tracing a Hybrid Extraction

Imagine uploading `invoice.pdf` with missing delivery date:

1. **01_raw_text_extraction.json**
   - Contains: "Invoice Date: 2024-01-15"
   - Missing: "Delivery Date" field
   
2. **02_llm_response_textual.json**
   ```json
   {
     "Invoice": {
       "invoice_date": "2024-01-15",
       "delivery_date": null  ← Missing!
     }
   }
   ```
   
3. **03_llama_ocr_markdown_hybrid.json**
   - Contains: "Delivery: 2024-01-20"
   
4. **04_llm_response_ocr_hybrid.json**
   ```json
   {
     "Invoice": {
       "invoice_date": "2024-01-15",
       "delivery_date": "2024-01-20"  ← Found it!
     }
   }
   ```
   
5. **05_final_merged_result.json**
   ```json
   {
     "Invoice": {
       "invoice_date": "2024-01-15",
       "delivery_date": "2024-01-20"  ← Merged from OCR
     }
   }
   ```

This allows you to see exactly where the data came from!

---

## 📝 Log Files

Detailed logs are also saved in `logs/pipeline.log`:

```bash
# View extraction logs
tail -100 logs/pipeline.log | grep "extraction"

# View specific run
cat logs/pipeline.log | grep "invoice_20240825_114530"
```

---

## ✅ Benefits

✓ **Debugging**: See exactly what each step of the pipeline outputs
✓ **Quality Assurance**: Verify extraction accuracy  
✓ **Audit Trail**: Track which extraction method was used
✓ **Performance Monitoring**: Identify slow extraction steps
✓ **Data Recovery**: Retrieve intermediate results if needed
