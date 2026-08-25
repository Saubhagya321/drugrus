from pathlib import Path
from llama_cloud import LlamaCloud
import os
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
from share_convert import convert

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

load_dotenv('.env')
LLAMA_API_KEY_1 = os.environ['LLAMA_API_KEY_1']
LLAMA_API_KEY_2 = os.environ['LLAMA_API_KEY_2']

# client = LlamaCloud(api_key=LLAMA_API_KEY_1)

def extract_ocr_data(file_like):
    """Extract OCR markdown from a PDF-like file."""
    client = LlamaCloud(api_key=LLAMA_API_KEY_1)
    logger.info("Starting Llama OCR extraction")
    logger.debug("Creating Llama parse file with primary API key")
    try:
        file_obj = client.files.create(file=file_like, purpose="parse")
        logger.info("Llama file created successfully: file_id=%s", file_obj.id)
    except Exception:
        logger.exception("Failed to create Llama file for OCR")
        raise

    # Raises on FAILED or CANCELLED. Tune polling_interval=, timeout= if needed.
    logger.info("Initiating Llama parse with primary API key: file_id=%s", file_obj.id)
    try:
        result = client.parsing.parse(
            file_id=file_obj.id,
            tier="agentic",
            version="latest",
            output_options={
                    "markdown": {"tables": {"output_tables_as_markdown": True}}
            },
            # expand: which fields to materialize (markdown_full, text_full, items, *_content_metadata, ...),
            expand=["markdown_full"],
        )
        logger.info("Llama parse completed successfully with primary API key: file_id=%s", file_obj.id)
    except Exception:
        logger.exception("Llama parse failed with primary API key; retrying with secondary API key")
        client = LlamaCloud(api_key=LLAMA_API_KEY_2)
        try:
            result = client.parsing.parse(
                file_id=file_obj.id,
                tier="agentic",
                version="latest",
                expand=["markdown_full"],
            )
            logger.info("Llama parse completed successfully with secondary API key: file_id=%s", file_obj.id)
        except Exception:
            logger.exception("Llama parse failed with secondary API key")
            raise

    logger.info("Llama OCR extraction done")
    content = result.markdown_full
    print(f"Llama parser output : {content}")
    logger.debug("Llama OCR markdown output: %s", content)

    # xml = convert(content)
    # print("*************************************************************************")
    # print(xml)

    # return xml
    return content
