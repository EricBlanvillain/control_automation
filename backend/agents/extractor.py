import os
from agno.agent import Agent
# Import necessary libraries for file reading
import docx
import openpyxl
# For PDF/OCR, integration is needed. Placeholder libraries:
# import fitz  # PyMuPDF for basic PDF text extraction
# import pytesseract # Example OCR library
# from PIL import Image # For processing images for OCR

# TODO: Research and implement Mistral OCR integration if required.
#       This might involve using a specific API, library, or a custom Agno tool.

class ExtractorAgent:
    """
    Agent 2: Extracts text from various document types (Word, PDF, Excel, TXT).
    Handles OCR for image-based PDFs.
    Contextualizes/organizes chunks (basic implementation).
    """
    def __init__(self):
        # Initialize Agno Agent if needed for advanced chunking/contextualization
        # self.agent = Agent(model=..., instructions=["Organize the extracted text chunks..."])
        pass # Placeholder

    def _extract_from_docx(self, file_path: str) -> str:
        """Extracts text from a .docx file."""
        try:
            doc = docx.Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            # Consider extracting text from tables as well if needed
            # for table in doc.tables:
            #     for row in table.rows:
            #         for cell in row.cells:
            #             full_text.append(cell.text)
            return "\n".join(full_text)
        except Exception as e:
            print(f"Extractor: Error reading DOCX {file_path}: {e}")
            return ""

    def _extract_from_xlsx(self, file_path: str) -> str:
        """Extracts text from an .xlsx file."""
        try:
            workbook = openpyxl.load_workbook(file_path, data_only=True) # data_only=True reads values not formulas
            full_text = []
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                full_text.append(f"--- Sheet: {sheet_name} ---")
                for row in sheet.iter_rows():
                    row_text = []
                    for cell in row:
                        if cell.value is not None:
                            row_text.append(str(cell.value))
                    if row_text:
                        full_text.append(" | ".join(row_text)) # Simple joining
            return "\n".join(full_text)
        except Exception as e:
            print(f"Extractor: Error reading XLSX {file_path}: {e}")
            return ""

    def _extract_from_pdf(self, file_path: str) -> str:
        """Extracts text from a .pdf file, attempting OCR if needed."""
        # This is a placeholder. Real implementation needs robust PDF handling and OCR.
        print("Extractor: PDF extraction needs specific implementation (PyMuPDF, OCR).")

        # Attempt basic text extraction (e.g., using PyMuPDF - needs install: pip install pymupdf)
        try:
            # import fitz
            # doc = fitz.open(file_path)
            # text = ""
            # for page in doc:
            #     text += page.get_text()
            # doc.close()
            # if text.strip(): # Check if basic extraction worked
            #     print("Extractor: Found text layer in PDF.")
            #     return text
            # else:
                # If no text layer, proceed to OCR (placeholder)
                print("Extractor: No text layer found or basic extraction failed. OCR needed.")
                # TODO: Implement OCR logic here (e.g., using pytesseract, Mistral API)
                # Example with pytesseract (needs install: pip install pytesseract Pillow, and tesseract executable)
                # text = ""
                # doc = fitz.open(file_path)
                # for page_num in range(len(doc)):
                #     page = doc.load_page(page_num)
                #     pix = page.get_pixmap()
                #     img_bytes = pix.tobytes("png")
                #     img = Image.open(io.BytesIO(img_bytes))
                #     text += pytesseract.image_to_string(img)
                # doc.close()
                # return text
                return "Error: OCR not implemented yet."
        except ImportError:
            print("Extractor: PDF processing library (e.g., PyMuPDF) not installed.")
            return "Error: PDF library missing."
        except Exception as e:
            print(f"Extractor: Error reading PDF {file_path}: {e}")
            return f"Error: PDF processing failed ({e})"

    def _extract_from_txt(self, file_path: str) -> str:
        """Extracts text from a plain .txt file."""
        try:
            # Read with utf-8 encoding, handle potential errors
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Extractor: Error reading TXT {file_path}: {e}")
            return ""

    def run(self, file_path: str) -> str:
        """
        Detects file type and calls the appropriate extraction method.
        Performs basic chunking/organization (currently just returns full text).
        """
        print(f"Extractor: Processing document: {file_path}")
        if not os.path.exists(file_path):
            print(f"Extractor: Error - File not found: {file_path}")
            return ""

        _, extension = os.path.splitext(file_path.lower())
        extracted_text = ""

        if extension == '.docx':
            extracted_text = self._extract_from_docx(file_path)
        elif extension == '.xlsx':
            extracted_text = self._extract_from_xlsx(file_path)
        elif extension == '.pdf':
            extracted_text = self._extract_from_pdf(file_path)
            # TODO: Add chunking logic if needed
        elif extension == '.txt':
            extracted_text = self._extract_from_txt(file_path)
        else:
            print(f"Extractor: Error - Unsupported file type: {extension}")
            return ""

        print(f"Extractor: Finished extraction. Text length: {len(extracted_text)}")
        # Simple return - enhance with chunking/contextualization as needed
        return extracted_text
