"""URL builders and form parameters for District Courts portal.

Portal: https://services.ecourts.gov.in/ecourtindia_v6/

The portal uses AJAX POST requests via a custom ajaxCall() wrapper.
All requests go to: BASE_URL/?p=<controller>/<action>
All requests include: ajax_req=true&app_token=<rotating_token>

Court hierarchy (4 levels):
  State -> District -> Court Complex -> Establishment (optional)
"""

from __future__ import annotations

import re

BASE_URL = "https://services.ecourts.gov.in/ecourtindia_v6"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/vendor/securimage/securimage_show.php"

# ---------------------------------------------------------------------------
# Anti-bot "delimeter" header (added by the portal ~2026-07-22)
# ---------------------------------------------------------------------------
#
# Every AJAX POST now has to carry a couple of custom headers, or the server
# answers with a generic "Oops! ... Invalid Request...!" page for *every*
# endpoint — including the CAPTCHA-free cascade dropdowns.
#
# The secret is not in a cookie or the HTML; it is a literal baked into
# ``js/components.js``, which the portal republishes with a new value every
# hour or so (the page references it with a ``?v=<epoch>`` cache-buster):
#
#     function ajaxCall(jsonobj)
#     {
#         var delimeter="b64ttds7eew4";
#         ...
#         headers: {
#             "delimeter": delimeter,
#             "Xgy786trbsd7y": delimeter
#         },
#
# So it cannot be pinned as a constant — it has to be scraped per session and
# re-scraped when it rotates mid-run.
#
# The *header names* rotate too, not just the secret value: the original pair
# was ``delimeter`` + a fixed ``abc: xyz`` decoy, and on 2026-08-04 the decoy
# was replaced by ``Xgy786trbsd7y`` carrying the same secret. Pinning the names
# broke the whole backend exactly the way pinning the value would have (#17).
# So we scrape the ``headers:`` block itself and reproduce whatever it sends,
# falling back to the last-known-good pair if the block can't be parsed.

#: Name of the JS variable holding the rotating secret.
DELIMETER_VAR = "delimeter"

#: Last-known-good header spec, used when the ``headers:`` block can't be
#: parsed. ``None`` means "send the rotating secret as this header's value".
AJAX_HEADER_FALLBACK: dict[str, str | None] = {DELIMETER_VAR: None, "Xgy786trbsd7y": None}

#: Locates a ``headers: { ... }`` object literal. Header objects never nest, so
#: ``[^{}]*`` keeps this anchored to a single block.
AJAX_HEADERS_BLOCK_RE = re.compile(r"headers\s*:\s*\{([^{}]*)\}")

#: One ``"name": value`` entry, where value is a quoted literal or a bare
#: identifier (the ``delimeter`` variable).
AJAX_HEADER_ENTRY_RE = re.compile(
    r"""["']([A-Za-z0-9_-]+)["']\s*:\s*(?:["']([^"']*)["']|([A-Za-z_$][\w$]*))"""
)

#: Locates the components.js reference (with its ``?v=`` cache-buster) in the
#: homepage HTML, so we fetch exactly the build the portal is serving.
COMPONENTS_JS_RE = re.compile(r"js/components\.js(?:\?v=\d+)?")

#: Extracts the rotating secret from components.js.
DELIMETER_RE = re.compile(r"""var\s+delimeter\s*=\s*["']([^"']+)["']""")

#: Fallback path when the homepage HTML has no components.js reference.
COMPONENTS_JS_PATH = "js/components.js"


def components_js_url(home_html: str = "") -> str:
    """Resolve the URL of the portal's ``components.js``.

    Prefers the exact (cache-busted) reference found in ``home_html`` so we
    read the same build the browser would; falls back to the bare path.
    """
    match = COMPONENTS_JS_RE.search(home_html or "")
    return f"{BASE_URL}/{match.group(0) if match else COMPONENTS_JS_PATH}"


def parse_delimeter(js_source: str) -> str:
    """Extract the rotating ``delimeter`` secret from components.js.

    Returns an empty string if the literal is absent — the caller then sends
    the request without it, which still yields a clear portal-side error
    rather than a confusing local exception.
    """
    match = DELIMETER_RE.search(js_source)
    return match.group(1) if match else ""


def parse_ajax_header_spec(js_source: str) -> dict[str, str | None]:
    """Extract the anti-bot request headers ``ajaxCall()`` sends.

    Returns a mapping of header name -> literal value, where ``None`` means
    "substitute the rotating secret". Returns an empty dict when no headers
    block referencing the secret is found, so the caller can fall back to
    :data:`AJAX_HEADER_FALLBACK` rather than silently sending nothing.
    """
    for block in AJAX_HEADERS_BLOCK_RE.findall(js_source):
        spec: dict[str, str | None] = {}
        for name, literal, identifier in AJAX_HEADER_ENTRY_RE.findall(block):
            if not identifier:
                spec[name] = literal
            elif identifier == DELIMETER_VAR:
                spec[name] = None
            # any other identifier is a value we can't resolve — skip it
        # The anti-bot block is the one that carries the secret; other ajax
        # calls in the file may have their own unrelated headers.
        if any(value is None for value in spec.values()):
            return spec
    return {}


def ajax_headers(delimeter: str, spec: dict[str, str | None] | None = None) -> dict[str, str]:
    """Build the anti-bot headers for an AJAX POST.

    Args:
        delimeter: The rotating secret scraped from components.js.
        spec: Header spec from :func:`parse_ajax_header_spec`. Falls back to
            :data:`AJAX_HEADER_FALLBACK` when empty or omitted.
    """
    headers: dict[str, str] = {}
    for name, literal in (spec or AJAX_HEADER_FALLBACK).items():
        if literal is not None:
            headers[name] = literal
        elif delimeter:
            headers[name] = delimeter
    return headers


# State codes for district courts. These are portal-internal identifiers with
# no external authority — they do NOT match the High Court state codes in
# courts.py, and they have drifted wholesale before (13/36 entries went stale,
# #25: Delhi was "7", which the live portal reassigned to Jharkhand — so the
# wrong code returned *plausible* data for the wrong state). This dict is only
# the offline fallback; ``DistrictCourtClient.list_states()`` scrapes the live
# ``sess_state_code`` dropdown, which is the source of truth.
# Snapshot verified against the live portal on 2026-08-23.
DISTRICT_STATES: dict[str, str] = {
    "Andaman and Nicobar": "28",
    "Andhra Pradesh": "2",
    "Arunachal Pradesh": "36",
    "Assam": "6",
    "Bihar": "8",
    "Chandigarh": "27",
    "Chhattisgarh": "18",
    "Delhi": "26",
    "Goa": "30",
    "Gujarat": "17",
    "Haryana": "14",
    "Himachal Pradesh": "5",
    "Jammu and Kashmir": "12",
    "Jharkhand": "7",
    "Karnataka": "3",
    "Kerala": "4",
    "Ladakh": "33",
    "Lakshadweep": "37",
    "Madhya Pradesh": "23",
    "Maharashtra": "1",
    "Manipur": "25",
    "Meghalaya": "21",
    "Mizoram": "19",
    "Nagaland": "34",
    "Odisha": "11",
    "Puducherry": "35",
    "Punjab": "22",
    "Rajasthan": "9",
    "Sikkim": "24",
    "Tamil Nadu": "10",
    "Telangana": "29",
    "The Dadra And Nagar Haveli And Daman And Diu": "38",
    "Tripura": "20",
    "Uttarakhand": "15",
    "Uttar Pradesh": "13",
    "West Bengal": "16",
}


def ajax_url(controller_action: str) -> str:
    """Build full AJAX URL for a controller/action pair."""
    return f"{BASE_URL}/?p={controller_action}"


# ---------------------------------------------------------------------------
# Cascade dropdown forms (no CAPTCHA needed)
# ---------------------------------------------------------------------------


def fill_district_form(*, state_code: str) -> dict[str, str]:
    """Fill districts dropdown for a state."""
    return {"state_code": state_code}


def fill_complex_form(*, state_code: str, dist_code: str) -> dict[str, str]:
    """Fill court complexes dropdown for a district."""
    return {"state_code": state_code, "dist_code": dist_code}


def fill_establishment_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
) -> dict[str, str]:
    """Fill establishments dropdown for a court complex."""
    return {
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
    }


def set_data_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
) -> dict[str, str]:
    """Store court selection in server session."""
    return {
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
    }


def fill_case_type_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    search_type: str = "c_no",
) -> dict[str, str]:
    """Fill case types dropdown."""
    return {
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
        "search_type": search_type,
    }


# ---------------------------------------------------------------------------
# Case status search forms
# ---------------------------------------------------------------------------


def case_status_by_cnr_form(*, cnr: str, captcha: str) -> dict[str, str]:
    """Build form data for a CNR lookup on the district portal.

    Derived from ``funViewCinoHistory()`` in ``js/searchByCNR.js``. The
    controller action is ``cnr_status/searchByCNR``. Unlike the case-number
    searches this needs no state/district/complex codes — a CNR identifies the
    establishment on its own — so it also needs no ``set_data`` court setup.

    The response is the usual AJAX envelope; the case page arrives as HTML in
    ``casetype_list``.

    Args:
        cnr: 16-character CNR, no hyphens or spaces.
        captcha: Solved CAPTCHA text.
    """
    return {
        "cino": cnr.strip().upper(),
        "fcaptcha_code": captcha,
    }


def case_status_by_number_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    case_type: str,
    case_number: str,
    year: str,
    captcha: str,
) -> dict[str, str]:
    """Form data for case status search by case number.

    The portal's ``submitCaseNo()`` JS does ``$('#search_case').serialize()``
    (which includes ``search_case_no`` from the form) AND **also** appends
    ``&case_no=<value>`` separately. The server validates against
    ``case_no`` — sending only ``search_case_no`` makes it complain
    ``Case Number is required..!``. We send both for parity.
    """
    return {
        "case_type": case_type,
        "search_case_no": case_number,
        "case_no": case_number,
        "rgyear": year,
        "case_captcha_code": captcha,
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
    }


def case_status_by_party_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    party_name: str,
    year: str,
    status_filter: str = "Both",
    captcha: str,
) -> dict[str, str]:
    """Form data for case status search by party name."""
    return {
        "petres_name": party_name,
        "rgyearP": year,
        "case_status": status_filter,
        "fcaptcha_code": captcha,
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
    }


#: ``under_sec`` input limit on the district form (the HC form allows 100).
SECTION_MAX_LEN = 15


def fill_act_type_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    search_act: str = "",
) -> dict[str, str]:
    """Fill the act dropdown for a complex/establishment (no CAPTCHA).

    Derived from ``fillActType()`` in ``js/common_header.js``. The list comes
    back as HTML option fragments under ``act_list``. The JS sends
    ``est_code`` only when the complex needs an establishment (flag ``Y``)
    and an empty string otherwise.
    """
    return {
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
        "search_act": search_act,
    }


def case_status_by_act_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    act_code: str,
    section: str = "",
    status_filter: str = "Pending",
    captcha: str,
) -> dict[str, str]:
    """Form data for case status search by act (``casestatus/submitAct``).

    Mirrors ``submitAct()`` in ``js/searchByCaseStatus.js``: the serialized
    ``frm_act`` form plus the court codes. Results arrive as HTML under
    ``act_data``.

    Raises:
        ValueError: On a status filter other than "Pending" or "Disposed" —
            the form is a two-way radio with no "Both".
    """
    if status_filter not in ("Pending", "Disposed"):
        raise ValueError(f"status_filter must be 'Pending' or 'Disposed', got {status_filter!r}")
    return {
        "search_act": "",
        "actcode": act_code,
        "under_sec": section,
        "case_status": status_filter,
        "act_captcha_code": captcha,
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
    }


# ---------------------------------------------------------------------------
# Court orders forms
# ---------------------------------------------------------------------------


def court_orders_by_number_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    case_type: str,
    case_number: str,
    year: str,
    captcha: str,
    order_type: str = "both",
) -> dict[str, str]:
    """Form data for court orders search by case number.

    The portal's ``courtorder/submitCaseNo`` JS appends ``case_no``,
    ``rgyear``, and ``radvalue`` *in addition* to the form-serialized
    ``search_case_no``, ``rgyearCaseOrder``, and ``frad``. The server
    reads the explicit appended fields. We send both names for parity.
    """
    return {
        "case_type": case_type,
        "search_case_no": case_number,
        "case_no": case_number,
        "rgyearCaseOrder": year,
        "rgyear": year,
        "frad": order_type,
        "radvalue": order_type,
        "order_case_captcha_code": captcha,
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex": court_complex_code,
        "court_complex_arr": "",
        "est_code": est_code,
    }


# ---------------------------------------------------------------------------
# Cause list form
# ---------------------------------------------------------------------------


def cause_list_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    court_no: str,
    court_name: str,
    causelist_date: str = "",
    civil: bool = True,
    captcha: str,
) -> dict[str, str]:
    """Form data for cause list query.

    The portal's ``submit_causelist()`` JS reads ``$("#CL_court_no
    option:selected").text()`` (the selected court's display label) and
    appends it as ``court_name_txt``. The server requires it — sending
    an empty value triggers ``Court Name is required..!``. The caller
    is responsible for passing both ``court_no`` (the option value /
    code) and ``court_name`` (the option label).
    :meth:`bharat_courts.districtcourts.client.DistrictCourtClient
    .list_cause_list_courts` returns a code → name mapping.
    """
    if not causelist_date:
        from datetime import date

        causelist_date = date.today().strftime("%d-%m-%Y")

    # Calculate selprevdays
    selprevdays = "0"
    from datetime import date as date_cls
    from datetime import datetime

    try:
        sel = datetime.strptime(causelist_date, "%d-%m-%Y").date()
        if sel < date_cls.today():
            selprevdays = "1"
    except ValueError:
        pass

    return {
        "CL_court_no": court_no,
        "causelist_date": causelist_date,
        "cause_list_captcha_code": captcha,
        "court_name_txt": court_name,
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
        "cicri": "civ" if civil else "cri",
        "selprevdays": selprevdays,
    }


def fill_cause_list_form(
    *,
    state_code: str,
    dist_code: str,
    court_complex_code: str,
    est_code: str = "",
    search_act: str = "",
) -> dict[str, str]:
    """Form data for the ``cause_list/fillCauseList`` dropdown loader.

    Returns the courts dropdown for a given complex/establishment as
    HTML option fragments under the ``cause_list`` JSON field.
    """
    return {
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
        "search_act": search_act,
    }
