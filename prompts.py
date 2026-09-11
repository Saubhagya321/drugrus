# - ProductCode MUST be populated first according to the Product Code Extraction Rules; populate candidateProdCode only with any additional code(s) from the line item that could reasonably represent a product identifier.

INVOICE_EXTRACTION_RULES = """
You are an 20+ experienced medical expert in extracting structured product details from medical documents like invoices. 
Carefully identify the product details(mentioned in output JSON schema) from the invoices.

Your task:
- Analyze the invoice content provided.
- Identify and extract values for the fields listed below. Infer fields even if written in another language.
- Country and currency must reflect the supplier (not the buyer), and must always be written in English regardless of the invoice's language.
- The invoice typically lists both a buyer (often DrugsRus Ltd.) and a supplier. Extract only the supplier's details, never the buyer's.
- Supplier name: prefer trading/brand name; fallback to legal entity. Maintain proper spaces between words where required. example: "TheSimplePharma" -> The Simple Pharma. 
- If you are not certain, do NOT guess. Return null instead of incorrect supplier values.
- The source document may be in ANY language, but the output field names must always follow the exact schema below.
- If a value is missing, return it as null.
- DO NOT skip any entry or product.
- invoiceDate format: dd/mm/yyyy, for example "16/10/2025".
- invoiceValue format: Float only.
- itempervalue : itempervalue represents the monetary value charged for a single unit for the product. extract ONLY the final unit price for one item. NEVER extract quantities, package sizes, percentages, product codes, tax values, discounts, or line totals.
- If a product appears in the invoice content but not in the table, include it in output.
- For SGS Pharma Magyarorszag Kft. supplier with invoiceNo. SGS-2025-171, do not miss the product "Colistimethat-sodium1MIU -20packs 1.55 -31 TAHK 0 -31" if table row collapse occurs.
- For Herba Chemosan supplier with invoiceNo. 9301591016 and total invoice value 24710.0, make the total product row count 16, with 13 row products for KCL(having 490 quantity).


Non-Product Row Exclusion Rules (CRITICAL):
- Some rows in the source text are bookkeeping/carry-forward artifacts, not real purchased products. NEVER include these in "InvoiceProducts":
  - Rows labeled "Subtotal", "Total", "Total excl. VAT", "Total amount", "VAT amount", "Balance", "Amount due", or equivalents in any language.
  - Page-continuation carry-forward rows, commonly labeled "Transport", "Report", "Übertrag", "Overdracht", "Brought forward", "Carried forward", or equivalents — these restate a running subtotal at the top/bottom of a page break and are NOT a purchased item. A strong signal is: the row has no genuine article/product code (garbled, placeholder, or all-digit noise instead of a real catalog code), quantity of 1, and its amount matches (or nearly matches) a subtotal shown elsewhere in the document.
  - Rows that are visually/textually corrupted (e.g. characters repeated many times in a row such as "TTTTrrrraaaannnn...") — this is a PDF rendering artifact of a bold/overlapping summary line, not a product description. Do NOT fabricate a product from it even if a clean label like "Transport" or "Subtotal" appears at the end of the garbled text.
- Do NOT count these excluded rows toward the Row Count Verification total below.

Row Count Verification (CRITICAL):
- Before producing the final output, first count the total number of GENUINE product line items visible across every page/table of the document, row by row from top to bottom (excluding the non-product rows above).
- Your "InvoiceProducts" array MUST contain exactly that many entries. Recount and correct your output before returning it if the counts do not match.
- Rows that look identical or near-identical to a previous row (same name, same quantity, same price) are still separate, distinct line items. NEVER merge, deduplicate, collapse, or drop repeated rows, and NEVER fabricate extra rows. Each row in the source table must map to exactly one entry in the output, in the same order as they appear.
- This applies across page breaks too: if a table continues onto the next page/image, continue counting and extracting without treating the page break as the end of the table.

Parsing guidance:
- Units are discrete tokens that MUST NOT be merged into "name". Examples: "100STK", "90X1ENDOS", ref.., "28x1ENDOS".
- If Description and Unit are concatenated, exclude the unit token from "name".
- "name" MUST always be extracted exactly for a given product as it is present in the actual Invoice line items content : include the full product description (brand/product name, strength/dosage such as "80MCG", and pack/form descriptors such as "60 HB", "60 DOSER") exactly as printed in line items.
- Do NOT truncate or shorten the product name across different runs. Do NOT partially extract only the brand name when a fuller description (strength, dosage, pack count, form) is present in the same line item — always include the complete description.


Detect the number format from the invoice:
- If you see a comma used as a decimal, for example 3,7605, or a number with both dot and comma, for example 11.281,50, it is EU-style.
- For EU-style numbers, treat . as a thousands separator and , as a decimal separator.
- Normalize EU-style numbers by removing thousands dots and converting , to . Example: 11.281,50 -> 11281.50, 3.000 -> 3000.
- If numbers use dot as decimal, for example 3.76, and no comma-decimal pattern exists, it is US/UK-style. Keep dots as decimals and do not remove them.

Product Code Extraction Rules:
- Product codes must be unique for each product within the same invoice.
- Extract product codes only from columns that represent a product identifier, such as article number, item code, item number, product code, code, CODE, PZN, PHZNR, SKU, catalog/reference number, or equivalent terms in any language. A column headed "REF" (or any localized abbreviation of "reference") IS a valid product code column — always treat it as such.
- If NO valid product code column exists, Extract the product code from the product description ONLY when it is explicitly labeled with terms such as ref., reference, article, art., item no., catalog no., SKU, PZN, PHZNR, or equivalent terms in any language.
  Example: Cellona Shoe size M (39-41) ref. 16474 1pc/box Lohmann → "productCode": "16474". Do not extract unlabeled numbers from product descriptions.
- Identify the product code column by meaning, not exact text matching. The column header may appear in any language, abbreviation, casing, or format.
- If a column clearly represents a product identifier, always extract its values as productCode.
- If a product code value starts with "*", remove the "*" and return only the remaining value.
- Product codes must be unique per product. If the same code value is assigned to two or more DIFFERENT products in the invoice (not just repeated for the same product across rows), the code is unreliable, do not consider it as Product Code.
- If a description includes something like CNK:1564789, extract and return the product code as 1564789.
- DO NOT extract codes from parentheses or from inline text unless they are clearly labeled with one of the valid rules defined above for product code identifier.
- Do NOT infer product codes from unrelated fields like EAN, HS Code, IEC, Code no., batch numbers, PO, expiry dates, or AB250332A as product code.
- For supplier EURO Serve, MUST keep the productCode as null.
- When a row shows both an EAN column and a REF column, productCode MUST come from the REF column (after stripping any leading "*") and the EAN value MUST go into candidateProdCode. Never leave productCode null just because REF has a "*" prefix or because there is also an EAN present.
-Some invoices mislabel their product-code column as "Country" or "Country Code" (a template/translation error on the supplier's part). If a column labeled "Country" or "Country Code" contains values that are NOT valid country codes/names (i.e. not 2-3 letter ISO codes like FR, DE, PT, GB, or full country names), but instead multi-digit numeric values, treat that column as the true Product Code column and extract its values as productCode.
- PRECEDENCE OVER FORMAT (CRITICAL): if the value comes from a column explicitly labeled as a product identifier (REFERENCE, REF, article number, item code, code, SKU, catalog/reference number, or equivalent terms in any language per the rules above), it MUST be used as productCode — even if the value happens to look like a barcode/GTIN/EAN (12-14 digits) or is a long numeric string. The barcode-like appearance of a value is NEVER a reason to demote it to candidateProdCode when it comes from a labeled identifier column.
- If the labeled identifier column (e.g. REFERENCE) shows multiple space-separated numeric groups on the same row (e.g. "34009 3004007 2"), concatenate all groups in order into a single string with no spaces and use that as productCode (e.g. "34009 3004007 2" -> "3400930040072"). Do this per row; do not carry the value over to unrelated rows.

Candidate Product Code Rules:
- Always fill productCode first, following the Product Code Extraction Rules above. productCode must contain only the single best-validated product identifier. Only after productCode is filled (or confirmed null per the rules above) should you consider candidateProdCode.
- candidateProdCode is a fallback list: any OTHER line-item value that could reasonably be a product identifier but was NOT selected as productCode (e.g. a secondary code, alternate reference number, or similar product code identifier on the same row).
- candidateProdCode must NEVER replace or repeat the value already used in productCode.
- Extract candidateProdCode values only from columns/text that look like genuine product identifiers — do not pull arbitrary unrelated numbers.
- If multiple candidate identifiers exist on the same line item, MUST return them all as an array, in the order they appear.
- If productCode is not null, candidateProdCode MUST contain at least one entry — re-inspect the line item carefully for a secondary identifier before leaving it empty.
- If the product name/description is preceded, on its own line within the same cell, by a long unlabeled numeric value in barcode/GTIN format (typically 12-14 digits, e.g.3400926776008) that is NOT the value of any labeled identifier column, treat it as a candidate product identifier and include it in candidateProdCode. Do NOT merge it into "name", and do NOT discard it just because it has no explicit label like "ref."/"art."/"EAN". This rule applies only when no labeled identifier column claimed the value as productCode above.
- quantity and itemPerValue values MUST be numeric types.

"""

INVOICE_SCHEMA = """
{
  "Invoice": {
    "invoiceNo": "...",
    "invoiceDate": "...",
    "country": "...",
    "currency": "...",
    "invoiceValue": ...,
    "supplierName": "..."
  },
  "InvoiceProducts": [
    {
      "quantity": ...,
      "productCode": "...",
      "candidateProdCode":["...", "..."],
      "name": "...",
      "itemPerValue": ...
    }
  ]
}
"""

_TEXT_INVOICE_SCHEMA = INVOICE_SCHEMA.replace("{", "{{").replace("}", "}}")

TEXT_INVOICE_PROMPT = f"""
{INVOICE_EXTRACTION_RULES}

Schema to extract:
{_TEXT_INVOICE_SCHEMA}

Document Text:
{{text}}

Return ONLY a JSON object following the schema above.
"""

# INVOICE_EXTRACTION_RULES = """                                           
#   You are an expert at extracting structured content from business 
#   documents like invoices.
 
#   Your task:
#   - Analyze the invoice XML provided.
#   - Identify and extract values for the fields listed below. Infer fields even if written in another language.
#   - Country and currency must reflect the supplier (not the buyer), and must always be written in English regardless of the invoice's language.
#   - The source document may be in ANY language, but the output field names must always follow the exact schema below.
 
#   XML Structure guidance:
#   - <metadata> contains invoice header fields (number, date, totals). 
#   - <recipient> is the BUYER (often DrugsRus Ltd.) — never use this as the
#   supplier.
#   - <line_items> contains the product rows grouped under <delivery> blocks. extract quantity, productcode,productname,itempervalue and candidateproductcode.
#   - <summary> contains tax and invoice total rows — these are NOT product
#   rows.
#   - <conditions> contains payment terms and footer fields.
 
#   Supplier Name Extraction (CRITICAL):
#   - The supplier is the company that ISSUED this invoice, not the buyer.
#   - Look for the supplier name in this priority order:
#     1. Any field in <conditions> or <metadata> that contains a company
#   name, legal entity, or trading name not matching the buyer.
#     2. Any reference to a logo, letterhead, or company identifier in the
#   document (e.g. "Herba Chemosan logo" → supplier is "Herba Chemosan").
#     3. Any company registration details, bank details (IBAN/BIC), UID, or
#   FN number that identify the issuing entity — extract the company name
#   associated with those details.
#     4. Any footer or boilerplate text naming the issuing company.
#   - Prefer trading/brand name over legal entity name.
#   - If the supplier name is genuinely absent from the XML with no inference
#    possible, return null. Do NOT guess.
 
#   Other rules:
#   - If a value is missing, return it as null.
#   - DO NOT skip any entry or product.
#   - invoiceDate format: dd/mm/yyyy, for example "16/10/2025".
#   - invoiceValue format: Float only.
#   - For SGS Pharma Magyarorszag Kft. supplier with invoiceNo. SGS-2025-171,
#    do not miss the product "Colistimethat-sodium1MIU -20packs 1.55 -31 TAHK
#    0 -31" if table row collapse occurs.
 
#   Row Count Verification:
 
#   Product extraction is a completeness task.
#   1. Read every <item> inside every <delivery> block from top to bottom in
#   the exact order it appears.
#   2. Every <item> corresponds to exactly ONE object in InvoiceProducts.
#   3. Treat every <item> as a distinct line item, even if multiple
#   consecutive items have identical values (same quantity, description,
#   price, amount, or product code). (CRITICAL)
#   4. Never merge, deduplicate, summarize, infer, split, fabricate, or omit
#   product rows. (CRITICAL)
#   5. Do NOT include <summary> rows (Umsatzsteuer, Rechnungsbetrag,
#   Abstimmsumme) as product rows.
#   6. Preserve the original row order exactly as it appears in the XML when
#   creating InvoiceProducts.
#   7. Before returning the final JSON, verify that:
#      - every <item> has been extracted exactly once;
#      - no <item> has been skipped;
#      - no extra product rows have been created;
#      - the number of objects in InvoiceProducts equals the total number of
# <item> elements in the XML.
 
#   Parsing guidance:
#   - "name" MUST always be extracted exactly as it appears in the
# <artikelbezeichnung> (or equivalent name field) of the line item: include
#    the full product description (brand/product name, strength/dosage,
#   pack/form descriptors) exactly as printed.
#   - Do NOT truncate or shorten the product name. Always include the
#   complete description.
 
#   Detect the number format from the invoice:
#   - If you see a comma used as a decimal, for example 3,7605, or a number
#   with both dot and comma, for example 11.281,50, it is EU-style.
#   - For EU-style numbers, treat . as a thousands separator and , as a
#   decimal separator.
#   - Normalize EU-style numbers by removing thousands dots and converting ,
#   to . Example: 11.281,50 -> 11281.50, 3.000 -> 3000.
#   - If numbers use dot as decimal, for example 3.76, and no comma-decimal
#   pattern exists, it is US/UK-style. Keep dots as decimals and do not
#   remove them.
 
# Product Code Extraction Rules:
# - Product codes must be unique for each product within the same invoice.
# - Extract product codes only from tag that represent a product identifier, such as article number, item code, item number, product code, PZN, PHZNR, SKU, catalog/reference number, or equivalent terms in any language.
# - Identify the product code tag by meaning, not exact text matching. The tag may appear in any language, abbreviation, casing, or format.
# - If a tag clearly represents a product identifier, always extract its values as productCode.
# - If no valid product code tag exists, extract the product code from the product description only when it is explicitly labeled with terms such as ref., reference, article, art., item no., catalog no., SKU, PZN, PHZNR, or equivalent terms in any language.
#   Example: Cellona Shoe size M (39-41) ref. 16474 1pc/box Lohmann → "productCode": "16474". Do not extract unlabeled numbers from product descriptions.
# - If a product code value starts with "*", remove the "*" and return only the remaining value.
# - Product codes must be unique per product. If the same code value is assigned to two or more DIFFERENT products in the invoice (not just repeated for the same product across rows), the code is unreliable, do not consider it as Product Code.
# - If a description includes something like CNK:1564789, extract and return the product code as 1564789.
# - DO NOT extract codes from parentheses or from inline text unless they are clearly labeled with one of the valid tag names above. Return productCode as null in that case.
# - Do NOT infer product codes from unrelated fields like EAN, HS Code, IEC, Code no., batch numbers, PO references, expiry dates, or AB250332A as product code. Return null.
# - For supplier EURO Serve, MUST keep the productCode as null.

# Candidate Product Code Rules:
# - Always fill productCode first, following the Product Code Extraction Rules above. productCode must contain only the single best-validated product identifier.
# - candidateProdCode is a fallback list: any OTHER line-item value that could reasonably be a product identifier but was NOT selected as productCode (e.g. a secondary code, alternate reference number, or similar identifier on the same row).
# - candidateProdCode must NEVER replace or repeat the value already used in productCode.
# - Extract candidateProdCode values only from tag/text that look like genuine product identifiers — do not pull arbitrary unrelated numbers.
# - If multiple candidate identifiers exist on the same line item, return them all as an array, in the order they appear.
# - Rule for when candidateProdCode may be empty: it may be an empty array ONLY when productCode itself is null. If productCode is not null, candidateProdCode MUST contain at least one entry — re-inspect the line item carefully for a secondary identifier before leaving it empty.

 
# quantity and itemPerValue values MUST be numeric types.
# """
 
# INVOICE_SCHEMA = """
#   {
#     "Invoice": {
#       "invoiceNo": "...",
#       "invoiceDate": "...",
#       "country": "...",
#       "currency": "...",
#       "invoiceValue": ...,
#       "supplierName": "..."
#     },
#     "InvoiceProducts": [
#       {
#         "quantity": ...,
#         "productCode": "...",
#         "candidateProdCode": ["...", "..."],
#         "name": "...",
#         "itemPerValue": ...
#       }
#     ]
#   }
#   """
 
# _XML_INVOICE_SCHEMA = INVOICE_SCHEMA.replace("{", "{{").replace("}",
#   "}}")
 
# TEXT_INVOICE_PROMPT = f"""
# {INVOICE_EXTRACTION_RULES}

# Schema to extract:
# {_XML_INVOICE_SCHEMA}

# Invoice XML:
# {{text}}

# Return ONLY a JSON object following the schema above.
# """


OCR_INVOICE_PROMPT = f"""
{INVOICE_EXTRACTION_RULES}

Schema to extract:
{INVOICE_SCHEMA}

Analyze the attached invoice images.

Return ONLY a JSON object following the schema above.
"""


COUNT_INVOICES_PROMPT = """
Analyze the following document and count the number of DISTINCT invoices present.

Detection indicators (a new invoice usually starts when you see):
- A new invoice/receipt number (e.g., Belegnummer, Invoice No, Rechnungsnummer, Factura, Numero fattura)
- A new invoice date paired with a new invoice number
- Repeated header blocks (company logo/address followed by invoice metadata)
- Explicit separators like "---", page break markers, or repeating "# RECHNUNG"/"# INVOICE" headers
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


def build_multi_invoice_prompt(count: int) -> str:
    """
    Build a dynamic invoice extraction prompt for `count` invoices.
    Reuses INVOICE_EXTRACTION_RULES; wraps INVOICE_SCHEMA in an Invoices array
    with an `index` field per invoice.
    """
    invoice_objects = []
    for i in range(count):
        obj = (
            "    {\n"
            f'      "index": {i},\n'
            '      "Invoice": {\n'
            '        "invoiceNo": "...",\n'
            '        "invoiceDate": "...",\n'
            '        "country": "...",\n'
            '        "currency": "...",\n'
            '        "invoiceValue": ...,\n'
            '        "supplierName": "..."\n'
            "      },\n"
            '      "InvoiceProducts": [\n'
            "        {\n"
            '          "quantity": ...,\n'
            '          "productCode": "...",\n'
            '          "candidateProdCode":["...", "..."],\n'
            '          "name": "...",\n'
            '          "itemPerValue": ...\n'
            "        }\n"
            "      ]\n"
            "    }"
        )
        invoice_objects.append(obj)

    dynamic_schema = (
        "{\n"
        '  "Invoices": [\n'
        + ",\n".join(invoice_objects)
        + "\n  ]\n"
        "}"
    )

    # Escape braces so PromptTemplate treats them as literals
    schema_escaped = dynamic_schema.replace("{", "{{").replace("}", "}}")

    prompt = f"""
{INVOICE_EXTRACTION_RULES}

IMPORTANT (Multi-Invoice Extraction):
- This document contains EXACTLY {count} invoice(s).
- You MUST extract ALL {count} invoice(s) as separate objects in the "Invoices" array.
- Each object MUST have an "index" field (0 to {count - 1}) preserving document order.
- Apply ALL extraction rules above INDEPENDENTLY to EACH invoice.
- Do NOT merge invoices. Do NOT skip any invoice. Do NOT combine products across invoices.
- Fill EVERY object in the array. If a field is missing for a given invoice, use null.

Schema to extract:
{schema_escaped}

Invoice content:
{{text}}

Return ONLY a JSON object following the schema above.
"""
    return prompt

