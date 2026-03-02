"""Registry of Indian courts with eCourts identifiers.

State codes are from the HC Services portal (hcservices.ecourts.gov.in).
These were verified by probing the fillHCBench endpoint.

Judgment codes are from the judgments.ecourts.gov.in portal, verified
against vanga/indian-high-court-judgments court-codes.json.
"""

from bharat_courts.models import Court, CourtType

# eCourts HC Services state codes — verified against live portal
# Judgment codes — verified against judgments.ecourts.gov.in
HIGH_COURTS: list[Court] = [
    Court(
        name="Allahabad High Court",
        code="allahabad",
        state_code="13",
        court_type=CourtType.HIGH_COURT,
        judgment_code="9",
    ),
    Court(
        name="Allahabad High Court, Lucknow Bench",
        code="allahabad-lucknow",
        state_code="13",
        court_type=CourtType.HIGH_COURT,
        bench="Lucknow",
        judgment_code="9",
    ),
    Court(
        name="Andhra Pradesh High Court",
        code="andhra",
        state_code="2",
        court_type=CourtType.HIGH_COURT,
        judgment_code="28",
    ),
    Court(
        name="Bombay High Court",
        code="bombay",
        state_code="1",
        court_type=CourtType.HIGH_COURT,
        judgment_code="27",
    ),
    Court(
        name="Bombay High Court, Nagpur Bench",
        code="bombay-nagpur",
        state_code="1",
        court_type=CourtType.HIGH_COURT,
        bench="Nagpur",
        judgment_code="27",
    ),
    Court(
        name="Bombay High Court, Aurangabad Bench",
        code="bombay-aurangabad",
        state_code="1",
        court_type=CourtType.HIGH_COURT,
        bench="Aurangabad",
        judgment_code="27",
    ),
    Court(
        name="Bombay High Court, Goa Bench",
        code="bombay-goa",
        state_code="1",
        court_type=CourtType.HIGH_COURT,
        bench="Goa",
        judgment_code="27",
    ),
    Court(
        name="Calcutta High Court",
        code="calcutta",
        state_code="16",
        court_type=CourtType.HIGH_COURT,
        judgment_code="19",
    ),
    Court(
        name="Chhattisgarh High Court",
        code="chhattisgarh",
        state_code="18",
        court_type=CourtType.HIGH_COURT,
        judgment_code="22",
    ),
    Court(
        name="Delhi High Court",
        code="delhi",
        state_code="26",
        court_type=CourtType.HIGH_COURT,
        judgment_code="7",
    ),
    Court(
        name="Gauhati High Court",
        code="gauhati",
        state_code="6",
        court_type=CourtType.HIGH_COURT,
        judgment_code="18",
    ),
    Court(
        name="Gujarat High Court",
        code="gujarat",
        state_code="17",
        court_type=CourtType.HIGH_COURT,
        judgment_code="24",
    ),
    Court(
        name="Himachal Pradesh High Court",
        code="himachal",
        state_code="5",
        court_type=CourtType.HIGH_COURT,
        judgment_code="2",
    ),
    Court(
        name="Jammu & Kashmir High Court",
        code="jammu",
        state_code="12",
        court_type=CourtType.HIGH_COURT,
        judgment_code="1",
    ),
    Court(
        name="Jharkhand High Court",
        code="jharkhand",
        state_code="7",
        court_type=CourtType.HIGH_COURT,
        judgment_code="20",
    ),
    Court(
        name="Karnataka High Court",
        code="karnataka",
        state_code="3",
        court_type=CourtType.HIGH_COURT,
        judgment_code="29",
    ),
    Court(
        name="Kerala High Court",
        code="kerala",
        state_code="4",
        court_type=CourtType.HIGH_COURT,
        judgment_code="32",
    ),
    Court(
        name="Madhya Pradesh High Court",
        code="mp",
        state_code="23",
        court_type=CourtType.HIGH_COURT,
        judgment_code="23",
    ),
    Court(
        name="Madras High Court",
        code="madras",
        state_code="10",
        court_type=CourtType.HIGH_COURT,
        judgment_code="33",
    ),
    Court(
        name="Manipur High Court",
        code="manipur",
        state_code="25",
        court_type=CourtType.HIGH_COURT,
        judgment_code="14",
    ),
    Court(
        name="Meghalaya High Court",
        code="meghalaya",
        state_code="21",
        court_type=CourtType.HIGH_COURT,
        judgment_code="17",
    ),
    Court(
        name="Orissa High Court",
        code="orissa",
        state_code="11",
        court_type=CourtType.HIGH_COURT,
        judgment_code="21",
    ),
    Court(
        name="Patna High Court",
        code="patna",
        state_code="8",
        court_type=CourtType.HIGH_COURT,
        judgment_code="10",
    ),
    Court(
        name="Punjab and Haryana High Court",
        code="punjab",
        state_code="22",
        court_type=CourtType.HIGH_COURT,
        judgment_code="3",
    ),
    Court(
        name="Rajasthan High Court",
        code="rajasthan",
        state_code="9",
        court_type=CourtType.HIGH_COURT,
        judgment_code="8",
    ),
    Court(
        name="Sikkim High Court",
        code="sikkim",
        state_code="24",
        court_type=CourtType.HIGH_COURT,
        judgment_code="11",
    ),
    Court(
        name="Telangana High Court",
        code="telangana",
        state_code="29",
        court_type=CourtType.HIGH_COURT,
        judgment_code="36",
    ),
    Court(
        name="Tripura High Court",
        code="tripura",
        state_code="20",
        court_type=CourtType.HIGH_COURT,
        judgment_code="16",
    ),
    Court(
        name="Uttarakhand High Court",
        code="uttarakhand",
        state_code="15",
        court_type=CourtType.HIGH_COURT,
        judgment_code="5",
    ),
]

SUPREME_COURT = Court(
    name="Supreme Court of India",
    code="sci",
    state_code="0",
    court_type=CourtType.SUPREME_COURT,
)

ALL_COURTS: list[Court] = [SUPREME_COURT] + HIGH_COURTS

# Lookup maps
_BY_CODE: dict[str, Court] = {c.code: c for c in ALL_COURTS}
_BY_NAME: dict[str, Court] = {c.name.lower(): c for c in ALL_COURTS}
_BY_JUDGMENT_CODE: dict[str, Court] = {
    c.judgment_code: c for c in ALL_COURTS if c.judgment_code and c.bench is None
}


def get_court(code: str) -> Court | None:
    """Look up a court by its code (e.g. 'delhi', 'bombay-nagpur', 'sci')."""
    return _BY_CODE.get(code.lower())


def get_court_by_name(name: str) -> Court | None:
    """Look up a court by name (case-insensitive)."""
    return _BY_NAME.get(name.lower())


def get_court_by_judgment_code(judgment_code: str) -> Court | None:
    """Look up a court by its judgments.ecourts.gov.in code.

    Returns the main court (not bench variants). For example,
    judgment_code="27" returns Bombay HC (not Nagpur/Aurangabad/Goa bench).
    """
    return _BY_JUDGMENT_CODE.get(judgment_code)


def list_high_courts() -> list[Court]:
    """Return all High Courts."""
    return list(HIGH_COURTS)


def list_all_courts() -> list[Court]:
    """Return all courts including Supreme Court."""
    return list(ALL_COURTS)
