"""URL builders and form parameter construction for HC Services portal.

Portal: https://hcservices.ecourts.gov.in/hcservices/

The portal uses AJAX POST requests to:
- cases_qry/index_qry.php — main query endpoint (with action_code param)
- cases_qry/o_civil_case_history.php — case history by case number
- cases/cases.php — cause list
- securimage/securimage_show.php — CAPTCHA image

All URLs are relative to the base: /hcservices/
The JS var caseQryURL = "cases_qry/"
"""

from __future__ import annotations

BASE_URL = "https://hcservices.ecourts.gov.in/hcservices"

# Endpoint paths
MAIN_PAGE_URL = f"{BASE_URL}/main.php"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/securimage/securimage_show.php"
INDEX_QRY_URL = f"{BASE_URL}/cases_qry/index_qry.php"
CASE_HISTORY_URL = f"{BASE_URL}/cases_qry/o_civil_case_history.php"
FILING_HISTORY_URL = f"{BASE_URL}/cases_qry/o_filing_case_history.php"
CAUSE_LIST_URL = f"{BASE_URL}/cases/cases.php"
COURT_ORDERS_URL = f"{BASE_URL}/cases_qry/index_qry.php"
SHOW_RECORDS_URL = f"{INDEX_QRY_URL}?action_code=showRecords"
FILL_CASE_TYPE_URL = f"{INDEX_QRY_URL}?action_code=fillCaseType"
PDF_DISPLAY_URL = f"{BASE_URL}/cases/display_pdf.php"


def fill_bench_form(*, state_code: str) -> dict[str, str]:
    """Get available benches for a High Court."""
    return {
        "action_code": "fillHCBench",
        "state_code": state_code,
        "appFlag": "web",
    }


def fill_case_type_form(
    *,
    state_code: str,
    court_code: str = "1",
) -> dict[str, str]:
    """Get available case types for a court.

    Based on portal behavior: the portal sends ``court_code`` and ``state_code``
    to ``index_qry.php?action_code=fillCaseType``.  ``court_code`` is the
    bench code from fillHCBench (e.g. "1" for principal bench).
    """
    return {
        "court_code": court_code,
        "state_code": state_code,
    }


def case_status_form(
    *,
    state_code: str,
    court_code: str = "1",
    case_type: str,
    case_number: str,
    year: str,
    captcha: str,
) -> dict[str, str]:
    """Build form data for case status search by case number.

    Derived from the portal's ``funShowRecords()`` JS function.
    The AJAX call posts to ``index_qry.php?action_code=showRecords``.

    Note: ``action_code`` goes in the URL query string, NOT the POST body.
    """
    return {
        "court_code": court_code,
        "state_code": state_code,
        "court_complex_code": court_code,
        "caseStatusSearchType": "CScaseNumber",
        "captcha": captcha,
        "case_type": case_type,
        "case_no": case_number,
        "rgyear": year,
        "caseNoType": "new",
        "displayOldCaseNo": "NO",
    }


def case_status_by_party_form(
    *,
    state_code: str,
    court_code: str = "1",
    petres_name: str,
    rgyear: str,
    captcha: str,
    status_filter: str = "Both",
) -> dict[str, str]:
    """Build form data for case status search by party name.

    Derived from the portal's ``funShowRecords()`` JS function.
    The AJAX call posts to ``index_qry.php?action_code=showRecords``.

    Note: ``rgyear`` is **mandatory** — the server returns ERROR_VAL
    if it is empty.

    Args:
        state_code: HC state code from courts registry.
        court_code: Bench code from fillHCBench (default "1" = principal).
        petres_name: Petitioner or respondent name (min 3 chars).
        rgyear: Registration year (mandatory, e.g. "2024").
        captcha: Solved CAPTCHA text.
        status_filter: "Pending", "Disposed", or "Both".
    """
    return {
        "court_code": court_code,
        "state_code": state_code,
        "court_complex_code": court_code,
        "caseStatusSearchType": "CSpartyName",
        "captcha": captcha,
        "f": status_filter,
        "petres_name": petres_name,
        "rgyear": rgyear,
    }


def validate_advocate_query(advocate_name: str | None, bar_code: str | None) -> None:
    """Raise unless exactly one of advocate name / bar code is given.

    Split out of :func:`case_status_by_advocate_form` so the client can check
    before spending a session and a CAPTCHA solve — with a manual solver that
    is a human waiting at a prompt — on a request that cannot be built.

    Raises:
        ValueError: If neither or both are given.
    """
    if bool(advocate_name) == bool(bar_code):
        raise ValueError("pass exactly one of advocate_name or bar_code")


def case_status_by_advocate_form(
    *,
    state_code: str,
    court_code: str = "1",
    captcha: str,
    advocate_name: str | None = None,
    bar_code: str | None = None,
    status_filter: str = "Both",
) -> dict[str, str]:
    """Build form data for case status search by advocate name or bar code.

    Derived from the portal's advocate branch of ``funShowRecords()``. The
    radio group ``radAdvt`` selects the mode and the JS maps it to a
    ``search_type`` value: 1 = advocate name, 2 = bar registration number.

    Note: ``caseStatusSearchType`` is ``CSAdvName`` for **both** modes. The
    portal also defines a ``CSAdvNamebar`` label, but sending it as the
    search type makes the server return ERROR_VAL — ``search_type`` is what
    selects name vs bar code.

    Args:
        state_code: HC state code from courts registry.
        court_code: Bench code from fillHCBench (default "1" = principal).
        captcha: Solved CAPTCHA text.
        advocate_name: Advocate name, full or partial (min 3 chars).
        bar_code: Bar registration number as ``<STATE>/<NUMBER>/<YEAR>``,
            e.g. "G/504/2011". Note this is *not* the bracketed id shown
            beside advocate names in results ("MR. HEMAL SHAH(6960)"); that
            is an internal court id.
        status_filter: "Pending", "Disposed", or "Both".

    Raises:
        ValueError: If neither or both of advocate_name / bar_code are given.
    """
    validate_advocate_query(advocate_name, bar_code)

    form = {
        "court_code": court_code,
        "state_code": state_code,
        "court_complex_code": court_code,
        "caseStatusSearchType": "CSAdvName",
        "captcha": captcha,
        "f": status_filter,
    }
    if advocate_name:
        form["advocate_name"] = advocate_name
        form["search_type"] = "1"
    else:
        form["adv_bar_state"] = bar_code or ""
        form["search_type"] = "2"
    return form


def advocate_cause_list_form(
    *,
    state_code: str,
    court_code: str = "1",
    captcha: str,
    bar_code: str,
    causelist_date: str,
) -> dict[str, str]:
    """Build form data for an advocate's cause list on a given date.

    This is ``search_type=3`` of the same advocate branch. Unlike the two
    search modes it takes a fixed ``f=date_case_list`` rather than a
    pending/disposed filter, and it requires a bar code — advocate name is
    not accepted for this mode.

    Note: the portal rejects dates more than one month ahead
    (``checkDateInpuWithNextMonth``).

    Args:
        state_code: HC state code from courts registry.
        court_code: Bench code from fillHCBench (default "1" = principal).
        captcha: Solved CAPTCHA text.
        bar_code: Bar registration number, e.g. "G/504/2011".
        causelist_date: Listing date as ``DD-MM-YYYY``.
    """
    return {
        "court_code": court_code,
        "state_code": state_code,
        "court_complex_code": court_code,
        "caseStatusSearchType": "CSAdvName",
        "captcha": captcha,
        "adv_bar_state": bar_code,
        "caselist_date_dmy": causelist_date,
        "search_type": "3",
        "f": "date_case_list",
    }


def case_status_by_cnr_form(*, cnr: str, captcha: str) -> dict[str, str]:
    """Build form data for a CNR lookup.

    Derived from the portal's ``funViewCinoHistory()``. Unlike every other
    search this takes no state or bench code — a CNR identifies the court on
    its own — and it answers with the full case-history page rather than the
    JSON envelope the other searches use.

    Note: ``caseStatusSearchType=CNRNumber`` must accompany the action code;
    without it the server replies ``ERROR_caseStatusSearchTypeBlank``.

    Args:
        cnr: 16-character CNR, no hyphens or spaces.
        captcha: Solved CAPTCHA text.
    """
    return {
        "cino": cnr.strip().upper(),
        "captcha": captcha,
        "appFlag": "web",
        "action_code": "fetchStateDistCourtNew",
        "caseStatusSearchType": "CNRNumber",
    }


def court_orders_form(
    *,
    state_code: str,
    court_code: str = "1",
    case_type: str = "",
    case_number: str = "",
    year: str = "",
    captcha: str,
) -> dict[str, str]:
    """Build form data for court orders search."""
    return {
        "court_code": court_code,
        "state_code": state_code,
        "court_complex_code": court_code,
        "caseStatusSearchType": "COCaseNumber",
        "captcha": captcha,
        "case_type": case_type,
        "case_no": case_number,
        "rgyear": year,
        "caseNoType": "new",
        "displayOldCaseNo": "NO",
    }


def cause_list_form(
    *,
    state_code: str,
    court_code: str = "1",
    captcha: str,
    causelist_date: str = "",
    flag: str = "civ_t",
    selprevdays: str = "0",
) -> dict[str, str]:
    """Build form data for cause list query via index_qry.php.

    Derived from the portal's showCivilCauseList() JS function.
    The AJAX call posts to cases_qry/index_qry.php with these params:
      action_code=showCauseList&flag=civ_t&selprevdays=0
      &captcha=<text>&state_code=<code>&court_code=<bench>
      &caseStatusSearchType=CLcauselist&appFlag=&causelist_date=DD-MM-YYYY

    Args:
        state_code: HC state code from courts registry.
        court_code: Bench code from fillHCBench (default "1" = principal).
        captcha: Solved CAPTCHA text.
        causelist_date: Date in DD-MM-YYYY format (defaults to today).
        flag: "civ_t" for civil, "cri_t" for criminal.
        selprevdays: "0" for today/future dates, "1" for past dates.
    """
    if not causelist_date:
        from datetime import date

        causelist_date = date.today().strftime("%d-%m-%Y")
    return {
        "action_code": "showCauseList",
        "flag": flag,
        "selprevdays": selprevdays,
        "captcha": captcha,
        "state_code": state_code,
        "court_code": court_code,
        "caseStatusSearchType": "CLcauselist",
        "appFlag": "",
        "causelist_date": causelist_date,
    }
