import logging

logger = logging.getLogger(__name__)


def drop_empty_invoices(result):
    """Remove multi-invoice entries that have no products AND no invoice number.

    Only touches multi-invoice results (dict with an "Invoices" list). Returns
    the result untouched for any other shape or on error.
    """
    if not isinstance(result, dict):
        return result

    invoices = result.get("Invoices")
    if not isinstance(invoices, list):
        return result

    kept = []
    dropped = 0
    for inv in invoices:
        if not isinstance(inv, dict):
            kept.append(inv)
            continue

        products = inv.get("InvoiceProducts") or []
        invoice_no = ""
        invoice_block = inv.get("Invoice")
        if isinstance(invoice_block, dict):
            invoice_no = invoice_block.get("invoiceNo") or ""
        if isinstance(invoice_no, str):
            invoice_no = invoice_no.strip()

        if not products and not invoice_no:
            dropped += 1
            continue
        kept.append(inv)

    if dropped:
        logger.info("Post-process: dropped %s empty invoice(s) from multi-invoice result", dropped)
        result["Invoices"] = kept
        if "count" in result:
            result["count"] = len(kept)

    return result
