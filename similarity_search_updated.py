from fastapi import FastAPI
from typing import List
from pydantic import BaseModel
import re
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

log_dir = Path(__file__).resolve().parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "pipeline.log"
log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
had_handlers = bool(root_logger.handlers)

has_pipeline_file_handler = any(
    isinstance(handler, RotatingFileHandler)
    and Path(getattr(handler, "baseFilename", "")).resolve() == log_file.resolve()
    for handler in root_logger.handlers
)
if not has_pipeline_file_handler:
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(file_handler)

if not had_handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

for noisy_logger in ["httpx", "httpcore", "openai", "urllib3"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# Load embedding model once at startup
logger.info("Loading sentence transformer model for similarity search")
model = SentenceTransformer("all-MiniLM-L6-v2")
logger.info("Sentence transformer model loaded")

app = FastAPI()

# -----------------------------
# Request Models
# -----------------------------

class Country(BaseModel):
    """Country details used in matching."""
    countryId: int
    countryCode: str
    countryName: str


class ActualRecord(BaseModel):
    """Actual product and its country context."""
    product: str
    invoiceCountry: Country
    supplierCountries: List[Country]


class CandidateRecord(BaseModel):
    """Supplier candidate product details."""
    product: str
    supplierProductDescription: str
    countryId: int
    countryCode: str
    countryName: str

class MatchRequest(BaseModel):
    actual: str
    candidates: List[str]

class MatchRequest_Updated(BaseModel):
    """Request payload for country-aware matching."""
    actual: str
    candidates: List[str] = []
    actualRecord: ActualRecord
    candidateRecords: List[CandidateRecord]


# -----------------------------
# Text Normalization
# -----------------------------
def normalize_text(text):
    """Normalize text before similarity checks."""
    text = text.upper()
    text = re.sub(r"[^A-Z0-9X ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -----------------------------
# Number Extraction
# -----------------------------
def extract_numbers_with_units(text):
    """Extract numbers and optional units from text."""
    matches = re.findall(r"(\d+\.?\d*)\s*([A-Z]*)", text.upper())

    result = []
    for num, unit in matches:
        if num:
            result.append((float(num), unit))

    return result


# -----------------------------
# Number Similarity
# -----------------------------
def number_score(actual, candidate):
    """Compare numeric values in actual and candidate text."""
    actual_nums = [num for num, _ in extract_numbers_with_units(actual)]
    candidate_nums = [num for num, _ in extract_numbers_with_units(candidate)]

    if not actual_nums or not candidate_nums:
        return 0

    total_score = 0

    for a in actual_nums:
        closest = min(candidate_nums, key=lambda c: abs(a - c))
        diff = abs(a - closest)
        total_score += max(0, 100 - diff * 20)

    return total_score / len(actual_nums)


# -----------------------------
# Fuzzy Similarity
# -----------------------------
def fuzzy_score(actual, candidate):
    """Calculate fuzzy text similarity."""
    return fuzz.token_sort_ratio(actual, candidate)


# -----------------------------
# Embedding Similarity
# -----------------------------
def embedding_score(actual, candidate):
    """Calculate semantic similarity using embeddings."""
    try:
        embeddings = model.encode([actual, candidate])
        return float(util.cos_sim(embeddings[0], embeddings[1]) * 100)
    except Exception:
        logger.exception("Embedding similarity failed")
        raise


# -----------------------------
# Hybrid Score
# -----------------------------
def hybrid_score(actual, candidate):
    """Calculate final weighted similarity score."""
    try:
        actual_norm = normalize_text(actual)
        candidate_norm = normalize_text(candidate)

        num = number_score(actual_norm, candidate_norm)
        fuzzy = fuzzy_score(actual_norm, candidate_norm)
        embed = embedding_score(actual_norm, candidate_norm)
        score = (
            0.5 * num +
            0.3 * fuzzy +
            0.2 * embed
        )
        logger.debug(
            "Hybrid score calculated: actual=%s candidate=%s number_score=%.2f fuzzy_score=%.2f embedding_score=%.2f hybrid_score=%.2f",
            actual_norm,
            candidate_norm,
            num,
            fuzzy,
            embed,
            score,
        )
        return score

    except Exception:
        logger.exception("Hybrid score calculation failed: actual=%s candidate=%s", actual, candidate)
        raise


# -----------------------------
# Supplier similarity matching based on descriptions 
# -----------------------------

# Best match selection 
def top_matches(actual, candidates, top_n=50):
    """Return top matches using similarity score only."""
    logger.info("Starting supplier similarity match: candidates=%s top_n=%s", len(candidates), top_n)
    logger.debug("Supplier similarity input: actual=%s candidates=%s", actual, candidates)
    try:
        scores = [(cand, hybrid_score(actual, cand)) for cand in candidates]
        scores.sort(key=lambda x: x[1], reverse=True)
        matches = scores[:top_n]
        logger.info("Supplier similarity match completed: returned_matches=%s", len(matches))
        logger.debug("Supplier similarity sorted matches=%s", matches)
        return matches
    except Exception:
        logger.exception("Supplier similarity match failed")
        raise


# -----------------------------
# Country-aware Ranking
# -----------------------------
def top_matches_updated(request: MatchRequest_Updated, top_n=50):
    """Return top matches using country priority and similarity."""
    logger.info("Starting country-aware matching: candidates=%s top_n=%s", len(request.candidateRecords), top_n)
    actual = request.actual

    # Highest priority country
    invoice_country = request.actualRecord.invoiceCountry.countryCode.upper()

    # Second priority countries
    supplier_countries = {
        country.countryCode.upper()
        for country in request.actualRecord.supplierCountries
    }
    logger.debug(
        "Country-aware matching priorities: actual=%s invoice_country=%s supplier_countries=%s",
        actual,
        invoice_country,
        sorted(supplier_countries),
    )

    stack1 = []   # Invoice country matches
    stack2 = []   # Supplier country matches
    stack3 = []   # Remaining countries

    try:
        for candidate in request.candidateRecords:

            description = (
                candidate.supplierProductDescription
                if candidate.supplierProductDescription
                else candidate.product
            )

            score = hybrid_score(actual, description)

            result = {
                "product": candidate.product,
                "supplierProductDescription": description,
                "countryId": candidate.countryId,
                "countryCode": candidate.countryCode,
                "countryName": candidate.countryName,
                "score": round(score, 2)
            }

            candidate_country = candidate.countryCode.upper()

            # Stack 1 - Exact invoice country
            if candidate_country == invoice_country:
                stack1.append(result)
                priority_stack = "invoice_country"

            # Stack 2 - Supplier countries (excluding invoice country)
            elif candidate_country in supplier_countries:
                stack2.append(result)
                priority_stack = "supplier_country"

            # Stack 3 - Other countries
            else:
                stack3.append(result)
                priority_stack = "other_country"

            logger.debug(
                "Candidate scored and assigned: product=%s country=%s priority_stack=%s score=%.2f description=%s",
                candidate.product,
                candidate_country,
                priority_stack,
                result["score"],
                description,
            )

        # Apply existing similarity ranking within each stack
        stack1.sort(key=lambda x: x["score"], reverse=True)
        stack2.sort(key=lambda x: x["score"], reverse=True)
        stack3.sort(key=lambda x: x["score"], reverse=True)

        logger.info(
            "Country-aware matching stacks sorted: invoice_country_matches=%s supplier_country_matches=%s other_country_matches=%s",
            len(stack1),
            len(stack2),
            len(stack3),
        )
        logger.debug("Invoice country stack=%s", stack1)
        logger.debug("Supplier country stack=%s", stack2)
        logger.debug("Other country stack=%s", stack3)

        # Final ranking
        final_results = stack1 + stack2 + stack3
        matches = final_results[:top_n]
        logger.info("Country-aware matching completed: returned_matches=%s", len(matches))
        logger.debug("Country-aware final matches=%s", matches)

        return matches
    except Exception:
        logger.exception("Country-aware matching failed")
        raise
