"""URL and form builders for Calcutta High Court portal.

Portal: https://calcuttahighcourt.gov.in/highcourt_order_search

The portal uses Laravel with CSRF tokens. Each search requires:
1. GET the search page to obtain a _token (CSRF) and session cookie
2. GET /captcha/default for the CAPTCHA image
3. POST /order_judgment_search with form data (AJAX, returns JSON)
4. POST /show_pdf with order_data to resolve PDF URL
"""

from __future__ import annotations

BASE_URL = "https://calcuttahighcourt.gov.in"

SEARCH_PAGE_URL = f"{BASE_URL}/highcourt_order_search"
CAPTCHA_URL = f"{BASE_URL}/captcha/default"
SEARCH_URL = f"{BASE_URL}/order_judgment_search"
SHOW_PDF_URL = f"{BASE_URL}/show_pdf"

# Establishment codes (bench → CIS code prefix)
ESTABLISHMENTS: dict[str, str] = {
    "appellate": "WBCHCA",
    "original": "WBCHCO",
    "jalpaiguri": "WBCHCJ",
    "portblair": "WBCHCP",
}


def search_form(
    *,
    token: str,
    establishment: str,
    case_type: str,
    case_number: str,
    year: str,
    captcha: str,
) -> dict[str, str]:
    """Build form data for order/judgment search.

    Args:
        token: CSRF token from the search page.
        establishment: CIS establishment code (e.g. "WBCHCA").
        case_type: Numeric case type code (e.g. "12" for WPA).
        case_number: Case registration number.
        year: Case year.
        captcha: Solved CAPTCHA text.
    """
    return {
        "_token": token,
        "order_establishment": establishment,
        "order_casetype": case_type,
        "order_reg_no": case_number,
        "order_year": year,
        "captcha": captcha,
    }


def show_pdf_form(*, token: str, order_data: str) -> dict[str, str]:
    """Build form data for resolving a PDF URL.

    Args:
        token: CSRF token from the search page.
        order_data: Opaque string from the show_order() JS call
            (format: ``order_num~case_no~seq~cino~year``).
    """
    return {
        "_token": token,
        "order_data": order_data,
    }
