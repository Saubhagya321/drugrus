from fastapi import FastAPI
from typing import List
from pydantic import BaseModel
import os
import re
import json
import math
from datetime import datetime
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

console_logging_enabled = os.environ.get('CONSOLE_LOGGING', 'true').strip().lower() != 'false'
if not had_handlers and console_logging_enabled:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

for noisy_logger in ["httpx", "httpcore", "openai", "urllib3"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

# When DEBUG_FILE_MODE is on, every match request writes a score-breakdown
# JSON to api_run/ showing exactly what number/fuzzy/keyword/embedding
# component contributed to each candidate's final score.
DEBUG_FILE_MODE = os.environ.get("DEBUG_FILE_MODE", "false").strip().lower() in ("1", "true", "yes")

API_RUN_DIR = Path(__file__).resolve().parent / "api_run"
API_RUN_DIR.mkdir(exist_ok=True)


def _safe_identity(identity: str) -> str:
    """Sanitize a free-text identity (supplier/product name) for use in a filename."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", identity or "").strip("_")
    return cleaned[:80] or "unknown"


def _save_match_debug_file(api_name: str, identity: str, entries: list) -> None:
    """Persist a per-candidate score breakdown for this match request under api_run/.

    Only runs when DEBUG_FILE_MODE is enabled via the environment, since this
    writes one file per request and is meant for debugging/score-tuning, not
    production traffic.
    """
    if not DEBUG_FILE_MODE:
        return
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = API_RUN_DIR / f"{api_name}_{_safe_identity(identity)}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "api": api_name,
            "identity": identity,
            "timestamp": datetime.now().isoformat(),
            "matches": entries,
        }
        filepath = run_dir / "score_breakdown.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Saved match score breakdown file: %s", filepath)
    except Exception:
        logger.exception("Failed to save match score breakdown file for identity=%s", identity)

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
    """Calculate fuzzy text similarity, robust to extra trailing tokens (legal suffixes etc.)."""
    return fuzz.WRatio(actual, candidate)


# -----------------------------
# Keyword (IDF-weighted) Similarity
# -----------------------------
def build_idf_table(candidate_texts):
    """Build a token -> IDF table over a candidate corpus.

    Common tokens across the corpus (e.g. "PHARMA", "LTD") get a low IDF so they
    stop dominating the score; rare, discriminative tokens (e.g. "AXOL") get a
    high IDF so a match on them counts for much more.
    """
    document_frequency = {}
    total_documents = len(candidate_texts)

    for text in candidate_texts:
        for token in set(text.split()):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    idf_table = {
        token: math.log((total_documents + 1) / (df + 1)) + 1
        for token, df in document_frequency.items()
    }
    idf_table["__default__"] = math.log(total_documents + 1) + 1
    return idf_table


POSITION_DECAY = 0.8  # each later word in `actual` carries 80% of the previous word's weight


PARTIAL_MATCH_THRESHOLD = 75  # min rapidfuzz partial_ratio (0-100) before a token pair earns any credit


def _best_token_match(token, candidate_tokens):
    """Best partial-match score of `token` against any candidate token, 0-1.

    Exact matches score 1.0. Otherwise, credit is given for one token being
    contained/overlapping within the other (e.g. "EURO" inside "EUROSERV"),
    discounted by a length-ratio penalty so short tokens can't cheaply
    "contain-match" long, unrelated words. A minimum partial_ratio threshold
    filters out coincidental letter overlap between otherwise unrelated words
    (e.g. "SERVE" vs "EURO" share letters but aren't a real match).
    """
    best = 0.0
    for ctoken in candidate_tokens:
        if token == ctoken:
            return 1.0
        partial = fuzz.partial_ratio(token, ctoken)
        if partial < PARTIAL_MATCH_THRESHOLD:
            continue
        length_ratio = min(len(token), len(ctoken)) / max(len(token), len(ctoken))
        score = (partial / 100) * length_ratio
        if score > best:
            best = score
    return best


def keyword_score(actual, candidate, idf_table):
    """Calculate IDF- and position-weighted token overlap between actual and candidate.

    Words are weighted by both rarity (IDF) and their position in `actual` - earlier
    words matter more, so a candidate sharing actual's leading word(s) outranks one
    that only matches a trailing/common word, even if raw token overlap is similar.
    Matches are partial-credit (via `_best_token_match`) rather than exact-only, so
    fused compound words (e.g. "EUROSERV") still get credit against "EURO"/"SERVE".
    """
    actual_tokens = actual.split()
    candidate_tokens = set(candidate.split())

    if not actual_tokens:
        return 0

    default_idf = idf_table.get("__default__", 1)

    total_weight = 0
    overlap_weight = 0
    for position, token in enumerate(actual_tokens):
        weight = idf_table.get(token, default_idf) * (POSITION_DECAY ** position)
        total_weight += weight
        overlap_weight += weight * _best_token_match(token, candidate_tokens)

    if total_weight == 0:
        return 0

    return (overlap_weight / total_weight) * 100


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
def hybrid_score(actual, candidate, idf_table, return_breakdown=False):
    """Calculate final weighted similarity score.

    When return_breakdown=True, also returns a dict showing each component's
    raw score and its weighted contribution to the final hybrid score, so
    callers can log/persist which factor drove a given match.
    """
    try:
        actual_norm = normalize_text(actual)
        candidate_norm = normalize_text(candidate)

        num = number_score(actual_norm, candidate_norm)
        fuzzy = fuzzy_score(actual_norm, candidate_norm)
        keyword = keyword_score(actual_norm, candidate_norm, idf_table)
        embed = embedding_score(actual_norm, candidate_norm)

        num_contribution = 0.10 * num
        fuzzy_contribution = 0.35 * fuzzy
        keyword_contribution = 0.30 * keyword
        embed_contribution = 0.25 * embed
        score = num_contribution + fuzzy_contribution + keyword_contribution + embed_contribution

        logger.debug(
            "Hybrid score calculated: actual=%s candidate=%s number_score=%.2f fuzzy_score=%.2f "
            "keyword_score=%.2f embedding_score=%.2f hybrid_score=%.2f",
            actual_norm,
            candidate_norm,
            num,
            fuzzy,
            keyword,
            embed,
            score,
        )

        if return_breakdown:
            breakdown = {
                "raw_scores": {
                    "number_score": round(num, 2),
                    "fuzzy_score": round(fuzzy, 2),
                    "keyword_score": round(keyword, 2),
                    "embedding_score": round(embed, 2),
                },
                "weighted_contributions": {
                    "number": round(num_contribution, 2),
                    "fuzzy": round(fuzzy_contribution, 2),
                    "keyword": round(keyword_contribution, 2),
                    "embedding": round(embed_contribution, 2),
                },
                "hybrid_score": round(score, 2),
            }
            return score, breakdown

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
        idf_table = build_idf_table([normalize_text(cand) for cand in candidates])

        debug_entries = []
        scores = []
        for cand in candidates:
            if DEBUG_FILE_MODE:
                score, breakdown = hybrid_score(actual, cand, idf_table, return_breakdown=True)
                debug_entries.append({"candidate": cand, "score": round(score, 2), "breakdown": breakdown})
            else:
                score = hybrid_score(actual, cand, idf_table)
            scores.append((cand, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        matches = scores[:top_n]
        logger.info("Supplier similarity match completed: returned_matches=%s", len(matches))
        logger.debug("Supplier similarity sorted matches=%s", matches)

        if DEBUG_FILE_MODE:
            debug_entries.sort(key=lambda e: e["score"], reverse=True)
            _save_match_debug_file("match-supplier", actual, debug_entries)

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
        descriptions = [
            candidate.supplierProductDescription if candidate.supplierProductDescription else candidate.product
            for candidate in request.candidateRecords
        ]
        idf_table = build_idf_table([normalize_text(d) for d in descriptions])

        debug_entries = []
        for candidate, description in zip(request.candidateRecords, descriptions):

            if DEBUG_FILE_MODE:
                score, breakdown = hybrid_score(actual, description, idf_table, return_breakdown=True)
            else:
                score = hybrid_score(actual, description, idf_table)
                breakdown = None

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

            if DEBUG_FILE_MODE:
                debug_entries.append(
                    {
                        "product": candidate.product,
                        "supplierProductDescription": description,
                        "countryCode": candidate.countryCode,
                        "priority_stack": priority_stack,
                        "score": round(score, 2),
                        "breakdown": breakdown,
                    }
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

        if DEBUG_FILE_MODE:
            debug_entries.sort(
                key=lambda e: (
                    {"invoice_country": 0, "supplier_country": 1, "other_country": 2}[e["priority_stack"]],
                    -e["score"],
                )
            )
            _save_match_debug_file("match-products", actual, debug_entries)

        return matches
    except Exception:
        logger.exception("Country-aware matching failed")
        raise
