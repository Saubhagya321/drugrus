import io
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import uvicorn
import pandas as pd
from typing import List
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from invoice_processing import extract_full_invoice_structure
from similarity_search_updated import top_matches, MatchRequest, top_matches_updated, MatchRequest_Updated
from middleware.post_process import drop_empty_invoices

# Windows consoles default to cp1252, which crashes on non-Latin1 invoice text (e.g. Polish/Baltic characters)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "pipeline.log"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
had_handlers = bool(root_logger.handlers)

has_pipeline_file_handler = any(
    isinstance(handler, RotatingFileHandler)
    and Path(getattr(handler, "baseFilename", "")).resolve() == LOG_FILE.resolve()
    for handler in root_logger.handlers
)
if not has_pipeline_file_handler:
    root_logger.addHandler(file_handler)

if not had_handlers:
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

for noisy_logger in ["httpx", "httpcore", "openai", "urllib3", "pdfminer", "psparser","sentence_transformers"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)


app = FastAPI(title="Invoice Extraction API")

# -------------------------------------------------------------------------------
# OpenAI unavailable/rate limit → 503 Service Unavailable
# Unexpected server error → 500 Internal Server Error
# Successful extraction → 200 OK
# ------------------------------------------------------------------------------------
 
@app.post("/extract-invoice")
async def extract_invoice(file: UploadFile = File(...)):
    """Extract invoice details from an uploaded file."""
    logger.info("Invoice extraction request received: filename=%s content_type=%s", file.filename, file.content_type)
    try:
        contents = await file.read()
        logger.debug("Invoice file read successfully: filename=%s size_bytes=%s", file.filename, len(contents))
        file_like = io.BytesIO(contents)
        logger.info("Passing invoice file to extraction pipeline")
        result = extract_full_invoice_structure(file_like, filename=file.filename)
        print(f"--------Final output--------- : {result}")
        logger.debug("Invoice extraction raw result: %s", result)

        if isinstance(result, dict) and result.get("success") is False:
            logger.info("Invoice extraction returned unsuccessful response: %s", result)
            return JSONResponse(
                content=result,
                status_code=503
            )
        result = drop_empty_invoices(result)
        logger.info("Invoice extraction completed successfully")
        return JSONResponse(content=result)

    except Exception as e:
        logger.exception("Invoice extraction API failed")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/match-supplier")
async def match_products(request: MatchRequest):
    """Return supplier product matches using text similarity."""
    logger.info("API=/match-supplier | identity=%s | time=%s", request.actual, datetime.now().isoformat())
    logger.debug("Supplier match actual=%s candidates=%s", request.actual, request.candidates)
    try:
        results = top_matches(request.actual, request.candidates, top_n=50)
        logger.info("Supplier match completed: returned_matches=%s", len(results))
        logger.debug("Supplier match results=%s", results)
        return {
            "actual": request.actual,
            "matches": [{"product": cand, "score": score} for cand, score in results]
        }
    except Exception:
        logger.exception("Supplier match API failed")
        return JSONResponse(
            content={"error": "Supplier matching failed"},
            status_code=500
        )

@app.post("/match-products")
async def match_products_updated(request: MatchRequest_Updated):
    """Return country-aware product matches."""
    logger.info("API=/match-products | identity=%s | time=%s", request.actual, datetime.now().isoformat())
    logger.info(
        "Country-aware product match request received: candidates=%s invoice_country=%s supplier_countries=%s",
        len(request.candidateRecords),
        request.actualRecord.invoiceCountry.countryCode,
        [country.countryCode for country in request.actualRecord.supplierCountries],
    )
    logger.debug("Country-aware product match request payload=%s", request.dict())
    try:
        results = top_matches_updated(request, top_n=50)
        logger.info("Country-aware product match completed: returned_matches=%s", len(results))
        logger.debug("Country-aware product match results=%s", results)

        matched_products = {
                    "actual": {
                        "product": request.actual,
                        "countryId": request.actualRecord.invoiceCountry.countryId,
                        "countryCode":request.actualRecord.invoiceCountry.countryCode,
                        "countryName": request.actualRecord.invoiceCountry.countryName,
                    },
                    "matches": [
                        {
                            "product": match["product"],
                            "countryId": match["countryId"],
                            "countryCode": match["countryCode"],
                            "countryName": match["countryName"],
                            "score": match["score"]
                        }
                        for match in results
                    ]
                }

        print(matched_products)

        return matched_products

        # return {
        #     "actual": request.actual,
        #     "matches": [
        #         {
        #             "product": match["product"],
        #             "score": match["score"]
        #         }
        #         for match in results
        #     ]
        # }
    except Exception:
        logger.exception("Country-aware product match API failed")
        return JSONResponse(
            content={"error": "Product matching failed"},
            status_code=500
        )

if __name__ == "__main__":
    try:
        logger.info("Starting Invoice Extraction API server; log_file=%s", LOG_FILE)
        uvicorn.run(app, host="0.0.0.0", port=8001)
    except Exception:
        logger.exception("Failed to start Invoice Extraction API server")
