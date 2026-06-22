# District Courts

`DistrictCourtClient` is the live client for the District Courts portal at
`services.ecourts.gov.in` — the national eCourts service that covers **700+
district and taluka courts** across every state and union territory. Use it for
live case status, court orders, and cause lists at the district level.

!!! info "When to use this client"
    Reach for `DistrictCourtClient` when the question is about a **district-court
    case** and needs **current** state — "what's the status of this case", "what
    are the latest orders", "show me tomorrow's cause list". For finding judgments
    (historical or by judge/keyword) start with the [`Judgments` facade](facade.md)
    instead. For High Court cases, see [High Courts](high-courts.md).

## The 4-level hierarchy

Unlike High Courts (which you address with a single static code via `get_court()`),
district courts are organised as a four-level cascade. You must resolve all four
levels before you can search:

```text
State  →  District  →  Court Complex  →  Establishment
 "8"       "1"          "1080010"          "2"
 Bihar     Patna        Civil Court        (a specific court within the complex)
```

- **State** — the state or UT (e.g. `"8"` = Bihar). 36 in total.
- **District** — a district within that state (e.g. `"1"` = Patna).
- **Court Complex** — a physical court complex within the district. A complex may
  contain one or many *establishments*.
- **Establishment** — a specific court within a complex. Only required for some
  complexes (see the note on the complex value format below).

Because these codes are not static and differ from district to district, you
**discover them dynamically** by walking the cascade — each step's output feeds
the next.

### The discovery flow

```text
list_states()                          → {"8": "Bihar", ...}
list_districts("8")                    → {"1": "Patna", ...}
list_complexes("8", "1")               → {"1080010@2,3,4@Y": "Civil Court, Patna Sadar", ...}
parse_complex_value("1080010@2,3,4@Y") → ("1080010", ["2","3","4"], True)
list_establishments("8","1","1080010") → {"2": "...", ...}   # only if flag is Y
list_case_types("8","1","1080010","2") → {"1": "Civil Suit", ...}
```

The discovery methods are **CAPTCHA-free** — only the actual searches
(`case_status`, `case_status_by_party`, `court_orders`, `cause_list`) require a
CAPTCHA, which the client solves and retries automatically.

!!! note "Court complex value format: `code@ests@flag`"
    `list_complexes()` returns dropdown **values** in the compound form
    `complex_code@est_codes@flag`, for example `1080010@2,3,4@Y`:

    - `1080010` — the raw complex code
    - `2,3,4` — the establishment codes contained in this complex
    - `Y` — the "needs establishment" flag (`Y` means you must pick an
      establishment; otherwise establishment selection is not required)

    Always run the raw value through
    `parse_complex_value()` before passing it to the search methods — they expect
    the **bare** `court_complex_code` (`1080010`), not the compound value.

## Method reference

All search methods take `state_code`, `dist_code`, `court_complex_code`, and an
optional `est_code` (resolved via the discovery methods above). Search methods are
keyword-only (`*`) — pass them by name.

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_states()` | No | `dict[str, str]` | All states/UTs `{code: name}` |
| `list_districts(state_code)` | No | `dict[str, str]` | Districts for a state |
| `list_complexes(state_code, dist_code)` | No | `dict[str, str]` | Court complexes; values are `code@ests@flag` |
| `list_establishments(state_code, dist_code, court_complex_code)` | No | `dict[str, str]` | Establishments (use when complex flag is `Y`) |
| `list_case_types(state_code, dist_code, court_complex_code, est_code="")` | No | `dict[str, str]` | Case type codes; keys are compound `"<case_type>^<est_code>"` |
| `case_status(*, state_code, dist_code, court_complex_code, est_code="", case_type, case_number, year)` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(*, state_code, dist_code, court_complex_code, est_code="", party_name, year, status_filter="Both")` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(*, state_code, dist_code, court_complex_code, est_code="", case_type, case_number, year)` | Yes | `list[CaseOrder]` | Orders for a case |
| `cause_list(*, state_code, dist_code, court_complex_code, est_code="", court_no, court_name="", causelist_date="", civil=True)` | Yes | `list[CauseListEntry]` | Cause-list entries for a court |
| `list_cause_list_courts(state_code, dist_code, court_complex_code, est_code="")` | No | `dict[str, str]` | Courts dropdown for cause-list lookup |

!!! tip "Helpful defaults"
    - `year` is **mandatory** for `case_status_by_party` (the server rejects an
      empty year), and `party_name` must be at least 3 characters.
    - `status_filter` accepts `"Pending"`, `"Disposed"`, or `"Both"` (default).
    - `cause_list` takes a `court_no` (the option *value* from
      `list_cause_list_courts`) and a `court_name`. If you leave `court_name`
      empty, the client looks it up for you from `court_no` — the portal validates
      against the display name, so this saves a manual step.
    - `causelist_date` is `DD-MM-YYYY` and defaults to today.

!!! warning "Case type codes are compound — don't strip the suffix"
    `list_case_types()` returns codes in the portal's compound
    `"<case_type>^<est_code>"` form (e.g. `"89^2": "ADMINISTRATIVE SUITE"`). Pass
    the **full** compound string back as `case_type` to `case_status` and
    `court_orders`. Stripping the `^…` suffix will break the lookup.

## Worked example

This walks the full cascade — discover the hierarchy, parse the complex value,
list case types, then run searches. CAPTCHA solving and retries happen
automatically when an [OCR solver](captcha.md) is configured (the default when
`bharat-courts[ocr]` is installed).

```python
import asyncio
from bharat_courts import DistrictCourtClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver
from bharat_courts.districtcourts.parser import parse_complex_value


async def main():
    solver = OCRCaptchaSolver()

    async with DistrictCourtClient(captcha_solver=solver) as client:
        # 1. Discover the court hierarchy (no CAPTCHA)
        states = await client.list_states()
        # {"8": "Bihar", "7": "Delhi", ...}

        districts = await client.list_districts("8")        # Bihar
        # {"1": "Patna", "35": "Gaya", ...}

        complexes = await client.list_complexes("8", "1")   # Patna
        # {"1080010@2,3,4@Y": "Civil Court, Patna Sadar", ...}

        # 2. Parse the complex value → (complex_code, est_codes, needs_establishment)
        complex_val = next(iter(complexes))
        complex_code, est_codes, needs_est = parse_complex_value(complex_val)
        est_code = est_codes[0] if needs_est else ""

        # 2b. If the complex needs an establishment, list them and pick one
        if needs_est:
            establishments = await client.list_establishments("8", "1", complex_code)
            # {"2": "Civil Judge Sr. Div.", ...}
            est_code = next(iter(establishments))

        # 3. Discover case types for this court (no CAPTCHA)
        case_types = await client.list_case_types("8", "1", complex_code, est_code)
        # {"1^2": "Civil Suit", "89^2": "ADMINISTRATIVE SUITE", ...}

        # 4. Search by party name (CAPTCHA auto-solved and retried)
        cases = await client.case_status_by_party(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            party_name="kumar", year="2024",
        )
        for c in cases:
            print(f"{c.case_number}: {c.petitioner} vs {c.respondent}  [{c.cnr_number}]")

        # 5. Search by case number
        by_number = await client.case_status(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            case_type="1", case_number="100", year="2024",
        )

        # 6. Get orders for a case
        orders = await client.court_orders(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            case_type="1", case_number="100", year="2024",
        )
        for o in orders:
            print(f"{o.order_date} | {o.order_type} | {o.judge} | {o.pdf_url}")

        # 7. Cause list — court_name is auto-resolved from court_no if omitted
        entries = await client.cause_list(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            court_no="1@2", civil=True,
        )
        for e in entries:
            print(f"{e.serial_number}. {e.case_number}: {e.petitioner} vs {e.respondent}")


asyncio.run(main())
```

### Parsing the complex value

`parse_complex_value(value)` lives in `bharat_courts.districtcourts.parser` and is
the bridge between the raw dropdown value and the bare codes the search methods
expect:

```python
from bharat_courts.districtcourts.parser import parse_complex_value

parse_complex_value("1080010@2,3,4@Y")
# → ("1080010", ["2", "3", "4"], True)   # needs an establishment

parse_complex_value("1080099@@N")
# → ("1080099", [], False)               # establishment not required
```

The third element is the **`needs_establishment`** boolean (the flag `Y`/`N`).
When it is `True`, call `list_establishments()` and pass a chosen `est_code` to the
search methods; when `False`, leave `est_code=""`.

## What you get back

| Method group | Model | Useful fields |
|---|---|---|
| `case_status`, `case_status_by_party` | `CaseInfo` | `case_number`, `case_type`, `cnr_number`, `petitioner`, `respondent`, `registration_date`, `status`, `next_hearing_date` |
| `court_orders` | `CaseOrder` | `order_date`, `order_type`, `judge`, `pdf_url` |
| `cause_list` | `CauseListEntry` | `serial_number`, `case_number`, `petitioner`, `respondent`, `advocate_petitioner`, `court_number`, `judge` |

!!! note "District cause lists return structured entries, not PDFs"
    Unlike the High Court Services portal (which returns one PDF per bench),
    district-court cause lists come back as individual `CauseListEntry` rows — one
    per listed case. There is no PDF to download for these.

District-court order PDFs (`CaseOrder.pdf_url`) are not always uploaded on
eCourts even when the case exists. The client returns the URL it finds; the
download itself may fail server-side if the file was never published.

## How it works under the hood

The portal is session-and-token driven. Each AJAX response carries a rotating
`app_token` that must accompany the next request, and the CAPTCHA is pinned to the
PHP session. The client handles all of this for you:

1. `GET` the home page to establish the `SERVICES_SESSID` cookie.
2. Fetch an initial `app_token`.
3. Walk the cascade dropdowns (`fillDistrict`, `fillcomplex`,
   `fillCourtEstablishment`, `fillCaseType`).
4. Store the court selection server-side (`set_data`) before any search.
5. Solve the CAPTCHA and submit the query.

On a CAPTCHA rejection the client **creates a fresh session** (new cookies, new
CAPTCHA), re-establishes the court selection, and retries — up to 5 attempts by
default. You do not manage tokens, cookies, or retries yourself.

## See also

- [CAPTCHA handling](captcha.md) — solver options and accuracy.
- [High Courts](high-courts.md) — the sibling client for HC Services.
- [Calcutta High Court](calcutta-hc.md) — direct-website client.
- [Clients API reference](../reference/clients.md) — full signatures.
