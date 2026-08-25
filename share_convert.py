import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


# ── HTML table parser ──────────────────────────────────────────────────────────

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._cur_row: list[str] | None = None
        self._cur_cell: str | None = None
        self._in_thead = False
        self.headers: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "thead":
            self._in_thead = True
        if tag == "tr":
            self._cur_row = []
        if tag in ("th", "td"):
            self._cur_cell = ""
            self._colspan = int(attrs.get("colspan", 1))

    def handle_endtag(self, tag):
        if tag == "thead":
            self._in_thead = False
        if tag in ("th", "td") and self._cur_cell is not None:
            cell = self._cur_cell.strip()
            if self._in_thead:
                self.headers.append(cell)
            else:
                self._cur_row.append(cell)
                for _ in range(self._colspan - 1):
                    self._cur_row.append("")
            self._cur_cell = None
        if tag == "tr" and self._cur_row is not None:
            if self._cur_row:
                self.rows.append(self._cur_row)
            self._cur_row = None

    def handle_data(self, data):
        if self._cur_cell is not None:
            self._cur_cell += data


def _parse_html_table(html: str) -> tuple[list[str], list[list[str]]]:
    p = TableParser()
    p.feed(html)
    return p.headers, p.rows


# ── Helpers ────────────────────────────────────────────────────────────────────

BOLD_KV = re.compile(r"\*\*(.+?)\*\*\s*[:\–\-]?\s*(.+)")
DELIVERY_RE = re.compile(r"^Lieferung\s+(\S+)/(\S+)$")
ORDER_RE    = re.compile(r"^Bestellung\s+(.+)$")
ABSTIMM_RE  = re.compile(r"^Abstimmsumme$")


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[\s/]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s or "field"


def _extract_metadata(text: str) -> dict[str, str]:
    return {
        m.group(1).strip().rstrip(":"): m.group(2).strip()
        for m in BOLD_KV.finditer(text)
    }


def _indent_xml(elem, level=0):
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad


# ── Core conversion ────────────────────────────────────────────────────────────

def convert(md_content: str) -> str:
    """
    Takes the full .md string (Llama-parser invoice output).
    Returns the XML as a string.
    """
    # Split around the HTML table
    table_match = re.search(r"(<table>.*?</table>)", md_content, re.DOTALL | re.IGNORECASE)
    if not table_match:
        raise ValueError("No <table> found in the provided content.")

    pre_table  = md_content[:table_match.start()]
    table_html = table_match.group(1)
    post_table = md_content[table_match.end():]

    # Metadata + address from the section before # RECHNUNG
    rechnung_pos = pre_table.find("# RECHNUNG")
    before_rechnung = pre_table[:rechnung_pos] if rechnung_pos != -1 else pre_table

    meta_header = _extract_metadata(before_rechnung)

    addr_lines = [
        line.strip() for line in before_rechnung.splitlines()
        if line.strip()
        and not re.match(r"\*\*.+\*\*", line.strip())
        and not line.strip().startswith("Llama parser")
    ]

    # Table
    tbl_headers, tbl_rows = _parse_html_table(table_html)

    # Group rows into deliveries
    deliveries: list[dict] = []
    cur_delivery: dict | None = None
    summary_rows: list[dict] = []
    n = len(tbl_headers)

    for row in tbl_rows:
        row = (row + [""] * n)[:n]
        collapsed = " ".join(c for c in row if c.strip())

        d = DELIVERY_RE.match(collapsed)
        o = ORDER_RE.match(collapsed)

        if d:
            cur_delivery = {"delivery_id": d.group(1), "delivery_date": d.group(2),
                            "order": "", "items": [], "subtotal": ""}
            deliveries.append(cur_delivery)
            continue
        if o and cur_delivery is not None:
            cur_delivery["order"] = o.group(1).strip()
            continue
        if any(ABSTIMM_RE.match(c) for c in row):
            if cur_delivery is not None:
                betrag_idx = tbl_headers.index("Betrag") if "Betrag" in tbl_headers else 4
                cur_delivery["subtotal"] = row[betrag_idx].strip()
            continue
        if row[1].strip() in ("Umsatzsteuer", "Rechnungsbetrag"):
            summary_rows.append(dict(zip(tbl_headers, row)))
            continue
        if row[0].strip() and cur_delivery is not None:
            cur_delivery["items"].append(dict(zip(tbl_headers, row)))

    # Conditions / footer
    conditions: dict[str, str] = {}
    cond_match = re.search(r"\*\*Zahlungsbedingung\*\*\s*:\s*(.+)", post_table)
    if cond_match:
        conditions["Zahlungsbedingung"] = cond_match.group(1).strip()

    after_sep = re.split(r"\n---\n", post_table, maxsplit=1)
    meta_footer = _extract_metadata(after_sep[-1]) if len(after_sep) > 1 else {}

    # Build XML
    root = ET.Element("invoice")

    hdr = ET.SubElement(root, "metadata")
    for k, v in meta_header.items():
        ET.SubElement(hdr, _slugify(k)).text = v

    rec = ET.SubElement(root, "recipient")
    for i, line in enumerate(addr_lines):
        ET.SubElement(rec, f"line_{i+1}").text = line

    body = ET.SubElement(root, "line_items")
    for dlv in deliveries:
        d_el = ET.SubElement(body, "delivery", id=dlv["delivery_id"], date=dlv["delivery_date"])
        ET.SubElement(d_el, "order").text = dlv["order"]
        items_el = ET.SubElement(d_el, "items")
        for item in dlv["items"]:
            it = ET.SubElement(items_el, "item")
            for col, val in item.items():
                ET.SubElement(it, _slugify(col)).text = val
        ET.SubElement(d_el, "subtotal").text = dlv["subtotal"]

    summ = ET.SubElement(root, "summary")
    for row in summary_rows:
        sr = ET.SubElement(summ, "row")
        for col, val in row.items():
            ET.SubElement(sr, _slugify(col)).text = val

    cond_el = ET.SubElement(root, "conditions")
    for k, v in conditions.items():
        ET.SubElement(cond_el, _slugify(k)).text = v
    for k, v in meta_footer.items():
        ET.SubElement(cond_el, _slugify(k)).text = v

    _indent_xml(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


# ── Demo when run directly ─────────────────────────────────────────────────────

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "extractor.md"
    md_content = open(path, encoding="utf-8").read()
    xml_str = convert(md_content)
    print(xml_str)
