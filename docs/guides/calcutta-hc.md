# Calcutta High Court (Direct Client)

`CalcuttaHCClient` talks **directly** to the official Calcutta High Court website
(`calcuttahighcourt.gov.in`) instead of going through the national eCourts portal.

Why a dedicated client? For Calcutta High Court matters, the court's own site has
**better PDF coverage** than the eCourts judgment portal — orders and judgments from
**September 2020 onwards** (the period covered by the court's CIS system) are reliably
available here, often when the eCourts copy is missing. If you practise before the
Calcutta High Court, this is usually the client you want.

!!! info "What this client does"
    Search a case by its case-type / number / year, get back the case metadata and the
    list of orders passed in it, then download any order PDF. It is CAPTCHA-gated (solved
    automatically when you have `bharat-courts[ocr]` installed) and rate-limited, like the
    other live clients.

## When to use it

| You want… | Use |
|---|---|
| Orders / judgment PDFs in a specific Calcutta HC case (Sept 2020 onward) | **`CalcuttaHCClient.search_orders`** |
| A judgment by judge / year / citation across all courts (historical) | [`Judgments().find(...)`](facade.md) (archive) |
| Full-text keyword search of HC judgments | [`JudgmentSearchClient`](judgment-search.md) |
| Live case status / next hearing for any HC | [`HCServicesClient`](high-courts.md) |

## Quick start

This example searches **WPA 12886 of 2024** on the Appellate Side and downloads the PDF
of every order that has one.

```python
import asyncio
from bharat_courts import CalcuttaHCClient


async def main():
    async with CalcuttaHCClient() as client:
        case_info, orders = await client.search_orders(
            case_type="12",        # numeric case-type code; "12" = WPA
            case_number="12886",
            year="2024",
            establishment="appellate",
        )

        if case_info:
            print(f"{case_info.case_number}: "
                  f"{case_info.petitioner} vs {case_info.respondent}")
            print(f"CNR: {case_info.cnr_number}  ({case_info.court_name})")

        for i, order in enumerate(orders):
            print(f"{order.order_date} | {order.order_type} | "
                  f"{order.judge} | {order.neutral_citation}")
            if order.pdf_url:
                pdf = await client.download_order_pdf(order.pdf_url)
                with open(f"wpa_12886_2024_order_{i}.pdf", "wb") as f:
                    f.write(pdf)
                print(f"  saved {len(pdf)} bytes")


asyncio.run(main())
```

!!! tip "No solver to configure"
    With `pip install bharat-courts[ocr]`, the client auto-detects the OCR CAPTCHA solver
    and retries on its own — you don't pass anything. See the
    [CAPTCHA guide](captcha.md) for manual, ONNX, or custom solvers.

## `search_orders`

```python
async def search_orders(
    self,
    *,
    case_type: str,
    case_number: str,
    year: str,
    establishment: str = "appellate",
    max_captcha_attempts: int = 5,
) -> tuple[CaseInfo | None, list[CaseOrder]]
```

Searches a single case and returns its metadata plus its orders.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `case_type` | `str` | required | Numeric case-type code (e.g. `"12"` for WPA). |
| `case_number` | `str` | required | Case registration number, e.g. `"12886"`. |
| `year` | `str` | required | Case year, e.g. `"2024"`. |
| `establishment` | `str` | `"appellate"` | Which bench/side — see table below. |
| `max_captcha_attempts` | `int` | `5` | CAPTCHA solve retries; each retry opens a fresh session. |

**Returns** a tuple `(CaseInfo | None, list[CaseOrder])`:

- The first element carries case-level metadata (CNR, parties, full case number, court
  name). It is `None` when nothing matched and no metadata could be recovered.
- The second element is the list of orders. It can be empty even when `CaseInfo` is
  present (a case exists but has no published orders yet).

!!! note "Always unpack the tuple"
    `search_orders` returns **two** values. Write
    `case_info, orders = await client.search_orders(...)` — not a single list.

### `establishment` values

The Calcutta High Court is split across four establishments. Pass the lowercase name:

| Value | Bench / side |
|---|---|
| `"appellate"` | Appellate Side (default) |
| `"original"` | Original Side |
| `"jalpaiguri"` | Circuit Bench at Jalpaiguri |
| `"portblair"` | Circuit Bench at Port Blair |

### About CAPTCHA retries

Each retry opens a brand-new session before fetching a fresh CAPTCHA image, because the
CAPTCHA is pinned to the server session. A wrong CAPTCHA comes back as an HTTP 422, which
the client treats as "retry"; genuine validation errors propagate. The default of 5
attempts keeps the all-fail rate negligible with OCR solving, at roughly 3–4 seconds of
overhead per retry.

## `download_order_pdf`

```python
async def download_order_pdf(self, pdf_url: str) -> bytes
```

Downloads an order/judgment PDF given the `pdf_url` from a `CaseOrder`. The download
itself needs no CAPTCHA. Returns raw PDF bytes.

| Parameter | Type | Description |
|---|---|---|
| `pdf_url` | `str` | The URL from `CaseOrder.pdf_url`. |

!!! warning "Validity check"
    If the server returns an error string instead of a real PDF, this method raises
    `RuntimeError` rather than writing junk to disk — it checks for the `%PDF` magic bytes
    at the head of the response. Guard your calls with `if order.pdf_url:` since not every
    order row has a resolvable PDF.

## What you get back: `CaseOrder`

Each order in the returned list is a `CaseOrder`. The fields most relevant here:

| Field | Type | Meaning |
|---|---|---|
| `order_date` | `date` | Date the order was passed. |
| `order_type` | `str` | `"Judgment"`, `"Order"`, or `"Interim Order"`. |
| `judge` | `str` | Judge(s) who passed the order. |
| `neutral_citation` | `str` | Neutral citation, when the court has assigned one. |
| `pdf_url` | `str` | URL to download the order PDF (may be empty). |
| `order_text` | `str` | Order text, when available. |
| `pdf_bytes` | `bytes \| None` | Populated only if you store the download yourself. |

The accompanying `CaseInfo` exposes `case_number`, `case_type`, `cnr_number`,
`petitioner`, `respondent`, and `court_name` (the court's own `side` label, e.g.
"Calcutta High Court - Appellate Side"). See the
[clients API reference](../reference/clients.md) for the complete signatures and the full
model definitions.

## Notes and limitations

- **Coverage starts September 2020.** Older matters predate the CIS system and are not
  available through this client. For historical Calcutta judgments, try the
  [archive via the facade](facade.md) (the Calcutta HC partition is included).
- **Case-type codes are numeric and court-specific.** `"12"` is WPA; you'll need the
  correct numeric code for other case types.
- **Rate limiting is built in** (about one second between requests by default) — see
  [configuration](../start/configuration.md) to tune it.

## See also

- [Live High Courts (eCourts) →](high-courts.md)
- [Judgment search (full-text) →](judgment-search.md)
- [The `Judgments` facade →](facade.md)
- [Clients API reference →](../reference/clients.md)
