"""URL builders and form parameter construction for Judgment Search portal.

Portal: https://judgments.ecourts.gov.in/pdfsearch/

The portal uses a session-based flow:
1. GET /pdfsearch/ — loads the search page and sets session cookies
2. GET /pdfsearch/vendor/securimage/securimage_show.php — fetches CAPTCHA image
3. POST /pdfsearch/?p=pdf_search/checkCaptcha — validates CAPTCHA (returns JSON)
4. POST /pdfsearch/?p=pdf_search/home — DataTables AJAX, returns JSON
   ``{"reportrow": {"aaData": [[serial, html], ...], "iTotalDisplayRecords": N},
       "app_token": "..."}``
5. POST /pdfsearch/?p=pdf_search/openpdfcaptcha — exchange the row's path for a
   per-session ``outputfile`` URL (returns JSON ``{"outputfile": "/pdfsearch/tmp/<hash>.pdf"}``)
6. GET https://judgments.ecourts.gov.in<outputfile> — actual PDF download

All AJAX calls send ``ajax_req=true&app_token=<token>`` and the response
includes a rotated ``app_token`` that must be used on the next call.
"""

from __future__ import annotations

from urllib.parse import urlencode

BASE_URL = "https://judgments.ecourts.gov.in/pdfsearch"
SITE_ROOT = "https://judgments.ecourts.gov.in"

MAIN_PAGE_URL = f"{BASE_URL}/"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/vendor/securimage/securimage_show.php"
CHECK_CAPTCHA_URL = f"{BASE_URL}/?p=pdf_search/checkCaptcha"
SEARCH_RESULTS_URL = f"{BASE_URL}/?p=pdf_search/home"
OPEN_PDF_CAPTCHA_URL = f"{BASE_URL}/?p=pdf_search/openpdfcaptcha"


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


def search_results_form(
    *,
    search_text: str,
    captcha: str,
    app_token: str,
    search_opt: str = "PHRASE",
    court_type: str = "2",
    page: int = 1,
    page_size: int = 10,
) -> str:
    """Build URL-encoded form body for the DataTables AJAX search call.

    The portal's DataTable wires both its standard pagination params
    (``sEcho``, ``iColumns``, ``iDisplayStart``, ``iDisplayLength``, ...)
    and a long list of search-form fields (``search_txt1``, ``pet_res``,
    ``state_code``, etc.). All of them are required — the controller
    treats missing fields as truthy ``"undefined"`` literals and returns
    a default empty result. The full list below mirrors the
    ``fnServerData`` callback in ``js/pdfsearch.js``.

    Pagination uses ``iDisplayStart = (page - 1) * page_size`` and
    ``iDisplayLength = page_size``.
    """
    start = max(0, (page - 1) * page_size)
    pairs: list[tuple[str, str]] = [
        # Core search fields (search_txt1 carries the user query).
        ("search_txt1", search_text),
        ("search_txt2", ""),
        ("search_txt3", ""),
        ("search_txt4", ""),
        ("search_txt5", ""),
        ("pet_res", ""),
        ("state_code", ""),
        ("state_code_li", ""),
        ("dist_code", "null"),
        ("case_no", ""),
        ("case_year", ""),
        ("from_date", ""),
        ("to_date", ""),
        ("judge_name", ""),
        ("reg_year", ""),
        ("fulltext_case_type", ""),
        ("int_fin_party_val", "undefined"),
        ("int_fin_case_val", "undefined"),
        ("int_fin_court_val", "undefined"),
        ("int_fin_decision_val", "undefined"),
        ("sel_search_by", "phrase"),
        ("sections", "undefined"),
        ("judge_txt", ""),
        ("act_txt", ""),
        ("section_txt", ""),
        ("judge_val", ""),
        ("act_val", ""),
        ("year_val", ""),
        ("judge_arr", ""),
        ("flag", ""),
        ("captcha", captcha),
        ("disp_nature", ""),
        ("search_opt", search_opt),
        ("date_val", ""),
        ("fcourt_type", court_type),
        ("citation_yr", ""),
        ("citation_vol", ""),
        ("citation_supl", ""),
        ("citation_page", ""),
        ("case_no1", ""),
        ("case_year1", ""),
        ("pet_res1", ""),
        ("fulltext_case_type1", ""),
        ("citation_keyword", ""),
        ("sel_lang", ""),
        ("proximity", ""),
        ("neu_cit_year", ""),
        ("neu_no", ""),
        # DataTables protocol fields.
        ("sEcho", str(page)),
        ("iColumns", "2"),
        ("sColumns", ",,"),
        ("iDisplayStart", str(start)),
        ("iDisplayLength", str(page_size)),
        ("mDataProp_0", "0"),
        ("mDataProp_1", "1"),
        ("sSearch", ""),
        ("bRegex", "false"),
        ("sSearch_0", ""),
        ("bRegex_0", "false"),
        ("bSearchable_0", "true"),
        ("sSearch_1", ""),
        ("bRegex_1", "false"),
        ("bSearchable_1", "true"),
        ("iSortingCols", "0"),
        # ajaxCall envelope.
        ("ajax_req", "true"),
        ("app_token", app_token),
    ]
    return urlencode(pairs)


def open_pdf_captcha_form(
    *,
    path: str,
    app_token: str,
    court_type: str = "2",
    val: str = "0",
    citation_year: str = "",
) -> str:
    """Build the form body for resolving a row's path → temp PDF URL.

    Strips the ``#page=...&search=...`` fragment from the row path before
    sending — the controller returns 405 if it's present.
    """
    clean_path = path.split("#", 1)[0]
    pairs = [
        ("val", val),
        ("lang_flg", ""),
        ("path", clean_path),
        ("citation_year", citation_year),
        ("fcourt_type", court_type),
        ("file_type", ""),
        ("nc_display", ""),
        ("ajax_req", "true"),
        ("app_token", app_token),
    ]
    return urlencode(pairs)
