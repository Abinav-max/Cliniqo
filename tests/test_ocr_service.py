import pytest

from services.ocr_service import LocalOCRService, OCRServiceError


def test_text_document_ocr():
    result = LocalOCRService().extract(b"Synthetic patient note", "note.txt", "text/plain")

    assert result.raw_text == "Synthetic patient note"


def test_blank_pdf_returns_controlled_ocr_error():
    from io import BytesIO

    from pypdf import PdfWriter

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)

    with pytest.raises(OCRServiceError, match="no extractable text"):
        LocalOCRService().extract(output.getvalue(), "blank.pdf", "application/pdf")


def test_image_ocr_without_tesseract_returns_controlled_error():
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")

    with pytest.raises(OCRServiceError):
        LocalOCRService().extract(output.getvalue(), "image.png", "image/png")