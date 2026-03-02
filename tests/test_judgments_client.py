"""Tests for Judgment Search portal client."""

from bharat_courts.judgments.client import _validate_pdf_bytes


class TestValidatePdfBytes:
    def test_valid_pdf(self):
        content = b"%PDF-1.4 some pdf content here" + b"\x00" * 500
        assert _validate_pdf_bytes(content) == content

    def test_empty_response(self):
        assert _validate_pdf_bytes(b"") is None

    def test_315_byte_error_page(self):
        content = b"x" * 315
        assert _validate_pdf_bytes(content) is None

    def test_non_pdf_content(self):
        content = b"<html>Not Found</html>" + b"\x00" * 500
        assert _validate_pdf_bytes(content) is None

    def test_minimal_valid_pdf(self):
        content = b"%PDF-1.7" + b"\x00" * 400
        assert _validate_pdf_bytes(content) == content
