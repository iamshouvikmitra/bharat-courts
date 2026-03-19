"""URL builders and form parameters for District Courts portal.

Portal: https://services.ecourts.gov.in/ecourtindia_v6/

The portal uses AJAX POST requests via a custom ajaxCall() wrapper.
All requests go to: BASE_URL/?p=<controller>/<action>
All requests include: ajax_req=true&app_token=<rotating_token>

Court hierarchy (4 levels):
  State -> District -> Court Complex -> Establishment (optional)
"""

from __future__ import annotations

BASE_URL = "https://services.ecourts.gov.in/ecourtindia_v6"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/vendor/securimage/securimage_show.php"

# State codes for district courts (from portal dropdown)
DISTRICT_STATES: dict[str, str] = {
    "Andaman and Nicobar": "28",
    "Andhra Pradesh": "2",
    "Arunachal Pradesh": "36",
    "Assam": "6",
    "Bihar": "8",
    "Chandigarh": "32",
    "Chhattisgarh": "18",
    "Delhi": "7",
    "Goa": "37",
    "Gujarat": "17",
    "Haryana": "10",
    "Himachal Pradesh": "5",
    "Jammu and Kashmir": "12",
    "Jharkhand": "33",
    "Karnataka": "3",
    "Kerala": "4",
    "Ladakh": "38",
    "Lakshadweep": "35",
    "Madhya Pradesh": "23",
    "Maharashtra": "27",
    "Manipur": "25",
    "Meghalaya": "21",
    "Mizoram": "34",
    "Nagaland": "39",
    "Odisha": "11",
    "Puducherry": "31",
    "Punjab": "22",
    "Rajasthan": "9",
    "Sikkim": "24",
    "Tamil Nadu": "30",
    "Telangana": "29",
    "The Dadra And Nagar Haveli And Daman And Diu": "40",
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
    """Form data for case status search by case number."""
    return {
        "case_type": case_type,
        "search_case_no": case_number,
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
    """Form data for court orders search by case number."""
    return {
        "case_type": case_type,
        "search_case_no": case_number,
        "rgyearCaseOrder": year,
        "frad": order_type,
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
    court_no: str = "",
    causelist_date: str = "",
    civil: bool = True,
    captcha: str,
) -> dict[str, str]:
    """Form data for cause list query."""
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
        "court_name_txt": "",
        "state_code": state_code,
        "dist_code": dist_code,
        "court_complex_code": court_complex_code,
        "est_code": est_code,
        "cicri": "civ" if civil else "cri",
        "selprevdays": selprevdays,
    }
