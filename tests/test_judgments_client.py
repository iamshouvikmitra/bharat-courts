"""Tests for Judgment Search portal client."""

from bharat_courts.judgments.client import JudgmentSearchClient, _validate_pdf_bytes


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


class TestTokenRotation:
    def _make_client(self) -> JudgmentSearchClient:
        from bharat_courts.captcha.manual import ManualCaptchaSolver

        return JudgmentSearchClient(captcha_solver=ManualCaptchaSolver())

    def test_update_token_from_response(self):
        client = self._make_client()
        assert client._app_token == ""
        client._update_token_from_response({"app_token": "tok_abc123"})
        assert client._app_token == "tok_abc123"

    def test_update_token_ignores_empty(self):
        client = self._make_client()
        client._app_token = "existing"
        client._update_token_from_response({"app_token": ""})
        assert client._app_token == "existing"

    def test_update_token_missing_key(self):
        client = self._make_client()
        client._app_token = "existing"
        client._update_token_from_response({})
        assert client._app_token == "existing"

    def test_is_session_expired_yes(self):
        client = self._make_client()
        assert client._is_session_expired({"session_expire": "Y"}) is True

    def test_is_session_expired_no(self):
        client = self._make_client()
        assert client._is_session_expired({"session_expire": "N"}) is False
        assert client._is_session_expired({}) is False

    def test_is_session_expired_error_message(self):
        client = self._make_client()
        assert client._is_session_expired({"errormsg": "Session expired"}) is True
        assert client._is_session_expired({"errormsg": "Invalid captcha"}) is False
