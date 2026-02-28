"""URL builders and form parameter construction for Judgment Search portal.

Portal: https://judgments.ecourts.gov.in/pdfsearch/

The portal uses a session-based flow:
1. GET /pdfsearch/ — loads the search page and sets session cookies
2. GET /pdfsearch/vendor/securimage/securimage_show.php — fetches CAPTCHA image
3. POST /pdfsearch/?p=pdf_search/checkCaptcha — validates CAPTCHA (returns JSON)
4. GET /pdfsearch/?p=pdf_search/home&text=...&... — loads search results page

All AJAX calls use the pattern: base_url/?p=<route>&app_token=<token>
"""

from __future__ import annotations

BASE_URL = "https://judgments.ecourts.gov.in/pdfsearch"

MAIN_PAGE_URL = f"{BASE_URL}/"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/vendor/securimage/securimage_show.php"
CHECK_CAPTCHA_URL = f"{BASE_URL}/?p=pdf_search/checkCaptcha"
SEARCH_RESULTS_URL = f"{BASE_URL}/"


def check_captcha_form(
    *,
    captcha: str,
    search_text: str,
    search_opt: str = "PHRASE",
) -> str:
    """Build URL-encoded form body for CAPTCHA validation.

    Returns a URL-encoded string (not dict) because the portal
    expects specific parameter ordering.
    """
    return (
        f"captcha={captcha}"
        f"&search_text={search_text}"
        f"&search_opt={search_opt}"
        f"&escr_flag="
        f"&proximity="
        f"&sel_lang="
        f"&ajax_req=true"
        f"&app_token="
    )


def search_results_params(
    *,
    search_text: str,
    captcha: str = "",
    search_opt: str = "PHRASE",
    court_type: str = "2",
    app_token: str = "",
    escr_flag: str = "",
) -> dict[str, str]:
    """Build query parameters for the search results page.

    Args:
        search_text: Keywords to search for.
        captcha: The solved CAPTCHA text.
        search_opt: "PHRASE", "ANY", or "ALL".
        court_type: "2" for High Courts, "3" for SCR (Supreme Court Reporter).
        app_token: Session token from checkCaptcha response.
        escr_flag: Set to "Y" for eSCR mode.
    """
    return {
        "p": "pdf_search/home",
        "text": search_text,
        "captcha": captcha,
        "search_opt": search_opt,
        "fcourt_type": court_type,
        "escr_flag": escr_flag,
        "proximity": "",
        "sel_lang": "",
        "app_token": app_token,
    }
