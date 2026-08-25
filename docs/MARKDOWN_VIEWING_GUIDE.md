# Viewing Llama OCR Markdown Output

## 📁 File Structure (Updated)

Now intermediate results are saved as **both JSON and Markdown**:

```
api_run/
└── invoice_20240825_121324/
    ├── 01_raw_text_extraction.json
    ├── 02_llama_ocr_markdown.json
    ├── 02_llama_ocr_markdown.md          ← NEW: Raw markdown file
    ├── 03_llm_response_ocr.json
    └── metadata.json
```

---

## 🔍 How to View Markdown Files

### Option 1: VS Code (Recommended)
**Best for editing and previewing**

1. Open VS Code
2. Navigate to `api_run/invoice_<timestamp>/`
3. Open the `.md` file (e.g., `02_llama_ocr_markdown.md`)
4. Click **Preview** button (top right) or press `Ctrl+Shift+V`

**Result**: Beautiful rendered markdown in a split pane

---

### Option 2: VS Code Extension (Enhanced)
**For fancy markdown rendering**

1. Install: `Markdown Preview Enhanced`
   - Open VS Code Extensions
   - Search "Markdown Preview Enhanced"
   - Install by Yiyi Wang

2. Right-click `.md` file → "Open Preview to the Side"

**Features**:
- Table formatting
- Code highlighting
- Export to HTML/PDF

---

### Option 3: Browser Preview
**Quick visual check**

```bash
# From project root
cd api_run
# Find the markdown file and open in browser:
start "02_llama_ocr_markdown.md"
```

Or manually open: `api_run/invoice_<timestamp>/02_llama_ocr_markdown.md` in your browser (won't render, but shows raw markdown)

---

### Option 4: Create HTML Preview (Automatic)
Let me add HTML preview generation...

---

## 📊 What You'll See in `.md` Files

### Raw Content (Unformatted):
```markdown
**Belegnummer**: 9301597438
**Belegdatum**: 26.06.2026

# RECHNUNG

| Menge | Artikelbezeichnung | PHZNR | Preis |
|-------|-------------------|-------|-------|
| 432   | NOVOMIX 30 FLEXP  | 2429687 | 31.80 |
```

### Rendered (In VS Code Preview):
```
Belegnummer: 9301597438
Belegdatum: 26.06.2026

RECHNUNG

┌────────┬──────────────────┬─────────┬────────┐
│ Menge  │ Artikelbezeichnung│ PHZNR   │ Preis  │
├────────┼──────────────────┼─────────┼────────┤
│ 432    │ NOVOMIX 30 FLEXP │ 2429687 │ 31.80  │
└────────┴──────────────────┴─────────┴────────┘
```

---

## ✅ LLM Processing

**Question**: Is markdown being sent correctly to LLM?
**Answer**: **YES ✓**

The LLM receives the clean string content (without JSON wrapper):
```python
# In code, before sending to LLM:
llm_input = llama_extraction  # This is the pure markdown string
result = process_invoice_data_with_llm(llm_input)
```

---

## 🔄 Data Flow

```
PDF Upload
    ↓
Llama Parse OCR
    ↓
Returns: Markdown String
    ├─→ Saved as: 02_llama_ocr_markdown.md (pure text)
    ├─→ Saved as: 02_llama_ocr_markdown.json (wrapped)
    └─→ Sent to LLM: Clean markdown string ✓
    ↓
LLM Parsing
    ↓
Output: Structured JSON
    ├─→ Saved as: 03_llm_response_ocr.json
    └─→ Sent to API: Structured invoice data ✓
```

---

## 🎯 Quick Checklist

- ✓ `.md` files are readable in VS Code preview
- ✓ LLM receives clean markdown strings
- ✓ JSON files keep full structured data
- ✓ Both formats saved for flexibility

---

## 📝 View Your Latest Run

```bash
# List recent runs (sorted by timestamp)
dir /O-D api_run | head -5

# Open latest markdown in VS Code
code "api_run\$(dir /B /O-D api_run | head -1)\02_llama_ocr_markdown.md"
```

---

## 🛠️ Troubleshooting

### Markdown looks weird in JSON viewer
→ Use the `.md` file instead (open in VS Code)

### Tables not aligned in JSON
→ Normal! Tables render correctly in VS Code preview

### Can't find .md file
→ Run a new extraction - previous runs didn't generate `.md` files
→ Restart server with updated code

### Markdown preview not showing
→ Install `Markdown Preview Enhanced` extension
→ Press `Ctrl+K V` to preview

---

## 💡 Pro Tips

1. **Compare versions**: Open two markdown files side-by-side
   ```
   code "api_run\invoice_1\02_llama_ocr_markdown.md" "api_run\invoice_2\02_llama_ocr_markdown.md"
   ```

2. **Export to HTML**: Right-click preview → "Export as HTML"

3. **Search across runs**:
   ```bash
   grep -r "NOVOMIX" api_run/ --include="*.md"
   ```

4. **Validate markdown**:
   ```bash
   # Online tool: https://www.markdownlint.com/
   ```

---

## Next Steps

1. ✅ Updated code saves both `.md` and `.json`
2. Install VS Code Markdown extension (optional but recommended)
3. Upload a new invoice
4. Check `api_run/<timestamp>/02_llama_ocr_markdown.md` in VS Code preview

Enjoy crystal-clear markdown viewing! 🎉
