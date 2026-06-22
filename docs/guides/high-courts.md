# High Courts via `HCServicesClient`

`HCServicesClient` is the live client for **hcservices.ecourts.gov.in** — the official
eCourts High Court Services portal. Use it for things that only the live portal can answer:
current case status, the next hearing date, in-progress orders, and today's cause list.

!!! tip "Looking for a judgment, not live status?"

    If you just want to *find a judgment* (by judge, party, year, citation, or CNR) and
    download its PDF, start with the federated [`Judgments` facade](facade.md) instead — it
    picks the historical [archive](archive.md) or the live portal for you and never needs a
    CAPTCHA for archive queries. Drop down to `HCServicesClient` when you need a portal-only
    feature: **case status, cause lists, or current orders**.

This client covers all 25 High Courts plus the Supreme Court, selected with a static court
code via `get_court(...)`.

## Picking a court

Every High Court is identified by a short code. Resolve it to a `Court` object once and pass
it to each method:

```python
from bharat_courts import get_court

court = get_court("delhi")     # or "bombay", "calcutta", "madras", ...
print(court.name)              # "Delhi High Court"
print(court.state_code)        # "26"
```

### Available High Courts

| Code | Court | State Code |
|------|-------|------------|
| `delhi` | Delhi High Court | 26 |
| `bombay` | Bombay High Court | 1 |
| `calcutta` | Calcutta High Court | 16 |
| `madras` | Madras High Court | 10 |
| `allahabad` | Allahabad High Court | 13 |
| `karnataka` | Karnataka High Court | 3 |
| `kerala` | Kerala High Court | 4 |
| `gujarat` | Gujarat High Court | 17 |
| `punjab` | Punjab & Haryana High Court | 22 |
| `rajasthan` | Rajasthan High Court | 9 |
| `telangana` | Telangana High Court | 29 |
| `andhra` | Andhra Pradesh High Court | 2 |
| `patna` | Patna High Court | 8 |
| `gauhati` | Gauhati High Court | 6 |
| `orissa` | Orissa High Court | 11 |
| `mp` | Madhya Pradesh High Court | 23 |
| `jharkhand` | Jharkhand High Court | 7 |
| `chhattisgarh` | Chhattisgarh High Court | 18 |
| `himachal` | Himachal Pradesh High Court | 5 |
| `uttarakhand` | Uttarakhand High Court | 15 |
| `jammu` | J&K High Court | 12 |
| `manipur` | Manipur High Court | 25 |
| `meghalaya` | Meghalaya High Court | 21 |
| `sikkim` | Sikkim High Court | 24 |
| `tripura` | Tripura High Court | 20 |
| `sci` | Supreme Court of India | 0 |

## CAPTCHA setup

The HC Services portal is CAPTCHA-gated. Search and order/cause-list methods need a CAPTCHA
solver; discovery methods (`list_benches`, `list_case_types`) and PDF download do not.

If you installed `bharat-courts[ocr]`, you don't have to do anything — the client
auto-detects the `ddddocr` solver. To be explicit (or to use a different solver), pass one in:

```python
from bharat_courts import HCServicesClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async with HCServicesClient(captcha_solver=OCRCaptchaSolver()) as client:
    ...
```

CAPTCHA failures are retried automatically — the client creates a fresh portal session on
each attempt because the image is pinned to the PHP session. See the
[CAPTCHA guide](captcha.md) for the full set of solvers (OCR, ONNX, manual, custom).

## Method reference

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_benches(court)` | No | `dict[str, str]` | Available benches (`{code: name}`) |
| `list_case_types(court, *, bench_code="1")` | No | `dict[str, str]` | Case type codes for a bench |
| `case_status(court, *, case_type, case_number, year, bench_code="1")` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(court, *, party_name, year, bench_code="1", status_filter="Both")` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(court, *, case_type, case_number, year, bench_code="1")` | Yes | `list[CaseOrder]` | Get orders for a case |
| `cause_list(court, *, civil=True, bench_code="1", causelist_date="")` | Yes | `list[CauseListPDF]` | Cause list PDFs (date format `DD-MM-YYYY`) |
| `download_order_pdf(pdf_url)` | No | `bytes` | Download an order/judgment PDF |

!!! warning "`year` is mandatory for party-name search"

    `case_status_by_party` **requires** the registration `year`. If you omit it, the portal
    returns an `ERROR_VAL` response rather than results — this is a server-side rule, not a
    CAPTCHA failure. (`case_status` and `court_orders` also take a required `year`.) The
    `party_name` should be at least 3 characters.

For the full data-model fields returned by each method, see the
[client reference](../reference/clients.md).

## Examples

All methods are async. Each example assumes `bharat-courts[ocr]` is installed so the default
solver is available.

### Discover benches and case types (no CAPTCHA)

Case type codes are numeric and vary by court, so discover them before searching. Benches and
case types are returned as `{code: name}` dictionaries and need no CAPTCHA.

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    async with HCServicesClient() as client:
        benches = await client.list_benches(court)
        # e.g. {"1": "Principal Bench at Delhi", ...}
        for code, name in benches.items():
            print(f"{code}: {name}")

        case_types = await client.list_case_types(court)  # default bench_code="1"
        # e.g. {"134": "W.P.(C)(CIVIL WRITS)-134", ...}
        for code, name in case_types.items():
            print(f"{code}: {name}")


asyncio.run(main())
```

### Search by party name (year mandatory)

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    async with HCServicesClient() as client:
        cases = await client.case_status_by_party(
            court,
            party_name="state",
            year="2024",            # mandatory — omitting it returns ERROR_VAL
            status_filter="Both",   # "Pending", "Disposed", or "Both"
        )
        for c in cases:
            print(f"{c.case_number}  {c.petitioner} vs {c.respondent}")
            print(f"  status: {c.status}  next hearing: {c.next_hearing_date}")


asyncio.run(main())
```

### Search by case number

Use a case type code from `list_case_types` (here `134` is W.P.(C) in Delhi):

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    async with HCServicesClient() as client:
        cases = await client.case_status(
            court,
            case_type="134",
            case_number="1",
            year="2024",
        )
        for c in cases:
            print(f"{c.case_number}  CNR={c.cnr_number}")
            print(f"  {c.petitioner} vs {c.respondent}  status={c.status}")


asyncio.run(main())
```

### Get court orders and download a PDF

`court_orders` returns `CaseOrder` objects carrying the PDF URL. Download with
`download_order_pdf` (no CAPTCHA — it reuses the same session):

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    async with HCServicesClient() as client:
        orders = await client.court_orders(
            court,
            case_type="134",
            case_number="1",
            year="2024",
        )
        for order in orders:
            print(f"{order.order_date}  {order.judge}")
            if order.pdf_url:
                pdf = await client.download_order_pdf(order.pdf_url)
                with open(f"order_{order.order_date}.pdf", "wb") as f:
                    f.write(pdf)


asyncio.run(main())
```

!!! note "Some order PDFs are not uploaded"

    Even when a case exists, an individual order PDF may not have been uploaded to eCourts.
    In that case `court_orders` still returns the URL, but `download_order_pdf` may raise
    because the server doesn't return a valid PDF. Handle that per order.

### Get the cause list

The cause list is returned as one PDF per bench/judge. Pass `civil=False` for the criminal
list, and a date in `DD-MM-YYYY` format (defaults to today if omitted):

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    async with HCServicesClient() as client:
        pdfs = await client.cause_list(
            court,
            civil=True,
            causelist_date="24-06-2026",   # DD-MM-YYYY; omit for today
        )
        for entry in pdfs:
            print(f"{entry.serial_number}  {entry.bench}  {entry.cause_list_type}")
            print(f"  {entry.pdf_url}")


asyncio.run(main())
```

## Notes and gotchas

- **All methods are async** — call them with `await` inside an `asyncio.run(...)` entry point.
- **Bench code** defaults to `"1"` (the principal bench). For courts with multiple benches
  (e.g. Allahabad / Lucknow), pass the code from `list_benches` to the search methods.
- **Case type codes are numeric and court-specific** — always discover them with
  `list_case_types` rather than guessing.
- **Rate limiting is built in** (1 second between requests by default). Tune it via
  [configuration](../start/configuration.md).
- **CAPTCHA accuracy** — the OCR solver is around 60% accurate per attempt, so the client
  retries with fresh sessions; the occasional slow search is expected. See the
  [CAPTCHA guide](captcha.md).

## See also

- [`Judgments` facade](facade.md) — the recommended default for finding judgments.
- [CAPTCHA solvers](captcha.md) — OCR, ONNX, manual, and custom.
- [Configuration](../start/configuration.md) — rate limits, timeouts, environment variables.
- [Client reference](../reference/clients.md) — full signatures and model fields.
