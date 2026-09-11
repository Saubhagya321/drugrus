import os
import json
import logging
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from llama_ocr_processing import extract_ocr_data
from prompts import TEXT_INVOICE_PROMPT, COUNT_INVOICES_PROMPT, build_multi_invoice_prompt
from openai import (
    RateLimitError,
    APIConnectionError,
    APITimeoutError
)

logger = logging.getLogger(__name__)
load_dotenv('.env')
OPEN_API_KEY = os.environ['OPEN_API_KEY']
OPENAI_MODEL = os.environ['OPENAI_MODEL']
COUNTER_MODEL = os.environ.get('COUNTER_MODEL', 'gpt-4o-mini')

API_RUN_DIR = Path(__file__).resolve().parent / "api_run"
API_RUN_DIR.mkdir(exist_ok=True)

def create_run_directory(filename: str) -> Path:
    """Create a directory for this API run with timestamp and filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = Path(filename).stem
    run_dir = API_RUN_DIR / f"{file_stem}_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

def save_intermediate_result(run_dir: Path, step_num: int, step_name: str, data: any) -> None:
    """Save intermediate result as JSON and markdown if applicable."""
    # Save as JSON
    json_filename = f"{step_num:02d}_{step_name}.json"
    json_filepath = run_dir / json_filename
    try:
        with open(json_filepath, 'w', encoding='utf-8') as f:
            if isinstance(data, str):
                json.dump({"content": data}, f, indent=2, ensure_ascii=False)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved intermediate result: {json_filename}")
    except Exception as e:
        logger.error(f"Failed to save intermediate result {json_filename}: {e}")

    # Save raw markdown if it's OCR output
    if "ocr" in step_name.lower() and isinstance(data, str):
        md_filename = f"{step_num:02d}_{step_name}.md"
        md_filepath = run_dir / md_filename
        try:
            with open(md_filepath, 'w', encoding='utf-8') as f:
                f.write(data)
            logger.info(f"Saved markdown file: {md_filename}")
        except Exception as e:
            logger.error(f"Failed to save markdown file {md_filename}: {e}")

def save_metadata(run_dir: Path, filename: str, extraction_method: str, success: bool) -> None:
    """Save metadata about the run."""
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "input_file": filename,
        "extraction_method": extraction_method,
        "success": success,
        "output_dir": str(run_dir)
    }
    filepath = run_dir / "metadata.json"
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Saved metadata to {filepath}")
    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")


def process_invoice_data_with_llm(text):
    logger.info("Starting textual invoice extraction with LLM")

    prompt = PromptTemplate.from_template(TEXT_INVOICE_PROMPT)
    
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=OPEN_API_KEY).bind(response_format={"type": "json_object"})
    parser = JsonOutputParser()

    chain = prompt | llm | parser

    try:
        logger.info("Invoking LLM for textual invoice extraction")
        result = chain.invoke({"text": text})
        return result
    except RateLimitError as e:
        logger.info("Textual LLM extraction failed")
        logger.exception("OpenAI rate limit/quota error")

        return {
            "success": False,
            "message": "OpenAI quota exceeded or too many requests.",
            "error": str(e)
        }
    except APIConnectionError:
        logger.exception("OpenAI connection error")

        return {
            "success": False,
            "message": "Unable to connect to OpenAI."
        }

    except APITimeoutError:
        logger.exception("OpenAI timeout")

        return {
            "success": False,
            "message": "OpenAI request timed out."
        }
    except Exception as e:
        logger.exception("Textual LLM extraction failed")
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}"
        }

def count_invoices(text: str) -> int:
    """Detect the number of invoices in the document using a cheap LLM. Fallback to 1."""
    logger.info("Detecting invoice count with counter LLM (model=%s)", COUNTER_MODEL)
    try:
        prompt = PromptTemplate.from_template(COUNT_INVOICES_PROMPT)
        llm = ChatOpenAI(
            model=COUNTER_MODEL,
            temperature=0,
            api_key=OPEN_API_KEY,
        ).bind(response_format={"type": "json_object"})
        parser = JsonOutputParser()
        chain = prompt | llm | parser
        result = chain.invoke({"text": text})
        count = int(result.get("count", 1))
        if count < 1:
            logger.warning("Counter returned %s, falling back to 1", count)
            return 1
        logger.info("Detected %s invoice(s)", count)
        return count
    except Exception as e:
        logger.exception("Invoice count detection failed, fallback to 1: %s", e)
        return 1


def process_invoice_data_with_llm_multi(text: str, count: int):
    """Extract `count` invoices in a single LLM call using a dynamic schema."""
    logger.info("Starting multi-invoice extraction with count=%s", count)
    dynamic_prompt = build_multi_invoice_prompt(count)

    prompt = PromptTemplate.from_template(dynamic_prompt)
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        temperature=0,
        api_key=OPEN_API_KEY,
    ).bind(response_format={"type": "json_object"})
    parser = JsonOutputParser()
    chain = prompt | llm | parser

    try:
        logger.info("Invoking extractor LLM for %s invoice(s)", count)
        result = chain.invoke({"text": text})
        return result
    except RateLimitError as e:
        logger.exception("OpenAI rate limit/quota error")
        return {
            "success": False,
            "message": "OpenAI quota exceeded or too many requests.",
            "error": str(e),
        }
    except APIConnectionError:
        logger.exception("OpenAI connection error")
        return {"success": False, "message": "Unable to connect to OpenAI."}
    except APITimeoutError:
        logger.exception("OpenAI timeout")
        return {"success": False, "message": "OpenAI request timed out."}
    except Exception as e:
        logger.exception("Multi-invoice LLM extraction failed")
        return {"success": False, "message": f"Unexpected error: {str(e)}"}


def extract_full_invoice_structure(file_like, filename: str = "invoice"):
    logger.info("Starting invoice structure extraction")
    run_dir = create_run_directory(filename)
    logger.info(f"Created run directory: {run_dir}")

    # 1. Extract content via Llama Parse OCR (always — no pdfplumber pre-pass)
    llama_extraction = extract_ocr_data(file_like)
    save_intermediate_result(run_dir, 1, "llama_ocr_markdown", llama_extraction)

    if not llama_extraction or not llama_extraction.strip():
        logger.warning("Llama Parse returned no content")
        save_metadata(run_dir, filename, "none", False)
        return {
            "success": False,
            "message": "Uploaded PDF is invalid, no content found"
        }

    # Step 2: Count invoices (Call 1 — cheap counter)
    count = count_invoices(llama_extraction)
    save_intermediate_result(run_dir, 2, "invoice_count_ocr", {"count": count})

    # Step 3: Extract all N invoices in one call (Call 2 — extractor)
    logger.info("Processing Llama Parse content through LLM (count=%s)", count)
    result = process_invoice_data_with_llm_multi(llama_extraction, count)
    save_intermediate_result(run_dir, 3, "llm_response_ocr", result)
    logger.info("Invoice extraction result received")

    if not result:
        save_metadata(run_dir, filename, "ocr_only", False)
        return {
            "success": False,
            "message": "Invoice extraction failed. No response received from LLM."
        }

    if result.get("success") is False:
        save_metadata(run_dir, filename, "ocr_only", False)
        return result

    invoices = result.get("Invoices", []) or []
    logger.info("Invoices extracted: expected=%s, returned=%s", count, len(invoices))
    print("Invoices returned:", len(invoices))

    result["count"] = count
    save_intermediate_result(run_dir, 4, "final_result", result)
    save_metadata(run_dir, filename, "ocr_only", True)
    logger.info("Invoice structure extraction complete: count=%s", count)
    return result

