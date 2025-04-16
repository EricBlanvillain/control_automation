import os
import logging
import io # Needed for OCR image processing if used
from typing import List, Tuple, Optional
from agno.agent import Agent
# Import necessary libraries for file reading
import docx
import openpyxl
# For PDF/OCR, integration is needed. Placeholder libraries:
import fitz  # PyMuPDF for basic PDF text extraction
# import pytesseract # Example OCR library
# from PIL import Image # For processing images for OCR

# Set up logger
logger = logging.getLogger(__name__)

# TODO: Research and implement Mistral OCR integration if required.
#       This might involve using a specific API, library, or a custom Agno tool.

# Configuration for chunking (can be overridden by env vars)
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200
CHUNK_SIZE = int(os.getenv("EXTRACTOR_CHUNK_SIZE", DEFAULT_CHUNK_SIZE))
CHUNK_OVERLAP = int(os.getenv("EXTRACTOR_CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP))

logger.info(f"Extractor configured with Chunk Size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")

# Define return type for extraction methods: (content: str | None, error_msg: str | None)
ExtractionResult = Tuple[Optional[str], Optional[str]]
# Define return type for the main run method: (chunks: List[str] | None, error_msg: str | None)
RunResult = Tuple[Optional[List[str]], Optional[str]]

class ExtractorAgent:
    """
    Agent 2: Extracts text from various document types (Word, PDF, Excel, TXT).
    Handles OCR for image-based PDFs.
    Contextualizes/organizes chunks (basic implementation).
    """
    def __init__(self):
        logger.info("Initializing ExtractorAgent...")
        # Initialize Agno Agent if needed for advanced chunking/contextualization
        # self.agent = Agent(model=..., instructions=["Organize the extracted text chunks..."])
        logger.info("ExtractorAgent initialized.")

    def _extract_from_docx(self, file_path: str) -> ExtractionResult:
        """Extracts text from a .docx file."""
        logger.debug(f"Extracting text from DOCX: {file_path}")
        try:
            doc = docx.Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            # TODO: Consider extracting text from tables as well if needed
            content = "\n".join(full_text)
            return content, None
        except Exception as e:
            error_msg = f"Error reading DOCX {file_path}: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    def _extract_from_xlsx(self, file_path: str) -> ExtractionResult:
        """Extracts text from an .xlsx file."""
        logger.debug(f"Extracting text from XLSX: {file_path}")
        workbook = None
        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
            full_text = []
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                logger.debug(f"--- Reading Sheet: {sheet_name} ---")
                for row in sheet.iter_rows():
                    row_text = [str(cell.value) for cell in row if cell.value is not None]
                    if row_text:
                        full_text.append(" | ".join(row_text))
            content = "\n".join(full_text)
            return content, None
        except Exception as e:
            error_msg = f"Error reading XLSX {file_path}: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg
        finally:
             if workbook:
                 workbook.close()
                 logger.debug(f"Closed XLSX workbook: {file_path}")

    def _extract_from_pdf(self, file_path: str) -> ExtractionResult:
        """Extracts text from a .pdf file using PyMuPDF. Returns error if only OCR is possible."""
        logger.info(f"Attempting PDF text extraction for {file_path} using PyMuPDF...")
        doc = None
        try:
            doc = fitz.open(file_path)
            extracted_text = ""
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                extracted_text += page.get_text()

            if extracted_text.strip():
                logger.info(f"Successfully extracted text layer from PDF: {file_path}")
                return extracted_text, None
            else:
                error_msg = "Error: No text layer found in PDF. OCR required but not implemented."
                logger.warning(f"{error_msg} for {file_path}.")
                return None, error_msg
        except ImportError:
            error_msg = "Error: PyMuPDF library missing."
            logger.critical("PyMuPDF (fitz) library not installed. PDF extraction unavailable.")
            return None, error_msg
        except Exception as e:
            error_msg = f"Error: PDF processing failed ({e})"
            logger.error(f"Error reading PDF {file_path}: {e}", exc_info=True)
            return None, error_msg
        finally:
            if doc:
                doc.close()
                logger.debug(f"Closed PDF document: {file_path}")

    def _extract_from_txt(self, file_path: str) -> ExtractionResult:
        """Extracts text from a plain .txt file."""
        logger.debug(f"Extracting text from TXT: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content, None
        except Exception as e:
            error_msg = f"Error reading TXT {file_path}: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    def _chunk_text(self, text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        """Splits text into chunks of a specified size with overlap."""
        # Input validation for chunking parameters
        if chunk_size <= 0:
             logger.error(f"Chunk size ({chunk_size}) must be positive. Cannot chunk.")
             # Return text as single chunk if chunking is impossible
             return [text]
        if chunk_overlap >= chunk_size:
             logger.warning(f"Chunk overlap ({chunk_overlap}) >= chunk size ({chunk_size}). Setting overlap to {chunk_size // 2}.")
             chunk_overlap = max(0, chunk_size // 2) # Ensure non-negative
        elif chunk_overlap < 0:
             logger.warning(f"Chunk overlap ({chunk_overlap}) is negative. Setting to 0.")
             chunk_overlap = 0

        if not text:
            logger.warning("Received empty text for chunking.")
            return []

        logger.debug(f"Chunking text (length {len(text)}) with size {chunk_size} and overlap {chunk_overlap}")
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            next_start = start + chunk_size - chunk_overlap
            # Prevent infinite loop
            if next_start <= start:
                 break
            start = next_start
        return chunks

    def run(self, file_path: str) -> RunResult:
        """
        Detects file type, calls the appropriate extraction method, and chunks the text.
        Returns: Tuple (Optional[List[str]], Optional[str])
                 - (list_of_chunks, None) on success.
                 - (None, error_message) on failure.
        """
        logger.info(f"Extractor starting processing for document: {file_path}")
        if not os.path.exists(file_path):
            error_msg = f"Error: File not found: {file_path}"
            logger.error(error_msg)
            return None, error_msg

        _, extension = os.path.splitext(file_path.lower())
        content: Optional[str] = None
        error_msg: Optional[str] = None

        logger.info(f"Detected file extension '{extension}'. Routing to appropriate extractor.")
        if extension == '.docx':
            content, error_msg = self._extract_from_docx(file_path)
        elif extension == '.xlsx':
            content, error_msg = self._extract_from_xlsx(file_path)
        elif extension == '.pdf':
            content, error_msg = self._extract_from_pdf(file_path)
        elif extension == '.txt':
            content, error_msg = self._extract_from_txt(file_path)
        else:
            error_msg = f"Error: Unsupported file type: {extension}"
            logger.error(error_msg)
            return None, error_msg

        # Handle extraction failure
        if error_msg:
             # Error already logged by the specific extraction method
             logger.error(f"Extraction failed for {file_path}. See previous logs.")
             return None, error_msg

        # Handle case where extraction succeeded but yielded no content (e.g., empty file)
        if content is None or content == "":
             logger.warning(f"Extraction yielded no text content for {file_path}. Returning empty chunk list.")
             return [], None # Success, but no chunks

        # Proceed with chunking if extraction was successful and produced content
        logger.info(f"Finished extraction for {file_path}. Raw text length: {len(content)}. Proceeding to chunking.")
        text_chunks = self._chunk_text(content, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

        logger.info(f"Split text into {len(text_chunks)} chunks.")
        return text_chunks, None # Success, return chunks
