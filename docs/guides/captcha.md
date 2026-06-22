# CAPTCHA Solving

The live eCourts portals — **HC Services**, **District Courts**, the **judgments**
portal, and **Calcutta High Court** — gate every search behind a
[Securimage](https://www.phpcaptcha.org/) CAPTCHA: a distorted six-character
alphanumeric image you normally have to read and type by hand.

bharat-courts makes this pluggable. Every live client accepts a `captcha_solver`,
and the SDK ships several ready-made solvers plus a tiny interface for writing your
own. In most cases you do nothing: install the recommended extra and the client
picks the best available solver for you.

!!! info "The archive needs no CAPTCHA"
    Only the *live* clients are CAPTCHA-gated. The historical
    [archive](archive.md) (AWS Open Data) and the `Judgments` facade's archive
    route are CAPTCHA-free, rate-limit-free, and need no solver at all. If your
    query can be answered from the archive, you avoid this whole topic.

## The `CaptchaSolver` interface

All solvers subclass a single abstract base class, `CaptchaSolver`, with one
async method:

```python
from abc import ABC, abstractmethod


class CaptchaSolver(ABC):
    @abstractmethod
    async def solve(self, image_bytes: bytes) -> str:
        """Given raw CAPTCHA image bytes, return the solved text."""
        ...
```

The client fetches the CAPTCHA image, hands the raw bytes to `solve()`, and uses
the returned string. That is the entire contract — anything that can turn image
bytes into a string can be a solver.

## The four built-in options

| Solver | Extra | Auth needed | Notes |
|---|---|---|---|
| `OCRCaptchaSolver` | `[ocr]` | None | **Recommended default.** ddddocr deep-learning recognition. |
| `ONNXCaptchaSolver` | `[onnx]` | `HF_TOKEN` | Lighter (onnxruntime); model downloaded from HuggingFace. |
| `ManualCaptchaSolver` | (bundled) | None | Prompts a human on stdin or via a callback. |
| Custom subclass | — | — | Bring your own model or paid solving service. |

### Auto-detection — you usually pass nothing

The live clients auto-detect the best available solver. If you installed
`bharat-courts[ocr]`, the default solver is `OCRCaptchaSolver` and you can omit
`captcha_solver` entirely:

```python
import asyncio
from bharat_courts import get_court, HCServicesClient


async def main():
    court = get_court("delhi")
    # No captcha_solver= passed — the client uses OCRCaptchaSolver automatically.
    async with HCServicesClient() as client:
        cases = await client.case_status(
            court, case_type="134", case_number="1", year="2024"
        )
        for c in cases:
            print(c.case_number, c.petitioner, "vs", c.respondent)


asyncio.run(main())
```

Pass an explicit `captcha_solver=` only when you want a different solver than the
auto-detected one (for example, forcing manual entry, or wiring in your own).

## Option 1 — `OCRCaptchaSolver` (recommended)

The default. Uses [ddddocr](https://github.com/sml2h3/ddddocr), a deep-learning
CAPTCHA recogniser that handles Securimage images well out of the box. No
authentication, no token, no external service.

```bash
pip install bharat-courts[ocr]
```

```python
from bharat_courts.captcha.ocr import OCRCaptchaSolver

solver = OCRCaptchaSolver()
```

Constructor options:

| Parameter | Default | Meaning |
|---|---|---|
| `preprocess` | `False` | Apply Pillow binarisation + median-filter cleanup before OCR. |
| `threshold` | `128` | Binarisation threshold (0–255), used only when `preprocess=True`. |

OCR is not perfect — a single decode lands somewhere around 60% of the time — but
this is by design. The solver validates its own output: if the decode isn't
exactly six alphanumeric characters, it returns an empty string instead of
guessing. The eCourts portals reject the wrong length anyway, so the empty string
signals the client to retry rather than waste a submission.

!!! tip "Retries are automatic"
    You don't loop manually. The live clients retry on a failed or rejected
    CAPTCHA up to a per-method `max_captcha_attempts` (default `3`), and because
    the CAPTCHA is pinned to the PHP session, the library spins up a **fresh
    session** for each retry so it gets a brand-new image. A few automatic
    retries usually clear a ~60%-per-attempt solver.

## Option 2 — `ONNXCaptchaSolver`

A lighter alternative that runs a pre-trained ONNX model on `onnxruntime` + Pillow
instead of pulling in ddddocr. Same six-character validation and retry behaviour
as the OCR solver.

```bash
pip install bharat-courts[onnx]
```

```python
import os
from bharat_courts.captcha.onnx import ONNXCaptchaSolver

os.environ["HF_TOKEN"] = "hf_..."  # or export it in your shell beforehand
solver = ONNXCaptchaSolver()
```

The model (`captchabreaker`) is downloaded from HuggingFace on first use and
cached at `~/.cache/bharat-courts/`. The constructor downloads eagerly so any
authentication error surfaces immediately rather than mid-search.

!!! warning "ONNXCaptchaSolver requires `HF_TOKEN`"
    The ONNX model is hosted on HuggingFace, which requires authentication to
    download. Set the `HF_TOKEN` environment variable before constructing the
    solver:

    ```bash
    export HF_TOKEN=hf_...
    ```

    Get a token at <https://huggingface.co/settings/tokens>. Without it, the
    solver raises a `RuntimeError` (HTTP 401) on construction. If you don't have
    a token, prefer `OCRCaptchaSolver`, which needs no authentication.

You can also point it at a local model file to skip the download entirely:

```python
solver = ONNXCaptchaSolver(model_path="/path/to/model.onnx")
```

## Option 3 — `ManualCaptchaSolver`

For interactive sessions or debugging, let a human read the CAPTCHA. By default
it writes the image to a temp file, prints the path to stderr, and waits for you
to type the text on stdin.

```python
from bharat_courts.captcha.manual import ManualCaptchaSolver

solver = ManualCaptchaSolver()  # saves image to a temp PNG, prompts on stdin
```

For GUI or web workflows, pass a callback that receives the image bytes and
returns (or awaits) the solved text — for example, to display the image in your
own UI and collect the answer:

```python
def my_callback(image_bytes: bytes) -> str:
    # show image_bytes to the user, collect their answer
    return show_in_ui_and_wait(image_bytes)


solver = ManualCaptchaSolver(callback=my_callback)
```

The callback may be sync or async — both are supported.

## Option 4 — Write your own solver

Anything that turns image bytes into a string can be a solver. Subclass
`CaptchaSolver` and implement the single async `solve` method. This is the hook
for a paid CAPTCHA-solving service, a model you host yourself, or a queue you push
images onto.

```python
from bharat_courts.captcha.base import CaptchaSolver


class MyServiceSolver(CaptchaSolver):
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def solve(self, image_bytes: bytes) -> str:
        # call your service, return the six-character text
        return await my_service.recognise(image_bytes, key=self._api_key)


# Use it like any built-in solver:
from bharat_courts import HCServicesClient

async with HCServicesClient(captcha_solver=MyServiceSolver(api_key="...")) as client:
    ...
```

!!! note "Validate your own output"
    The built-in solvers return an empty string when the decode isn't a valid
    six-character alphanumeric, which the client treats as "retry with a fresh
    image." If you write your own solver, returning `""` on low-confidence
    output gives you the same free retry instead of burning an attempt on a bad
    guess.

## Why retries use fresh sessions

The CAPTCHA is **pinned to the PHP session** on the eCourts side: the image you
were shown is only valid for the cookie you were issued. You can't simply ask for
a new image on the same session and re-submit. The live clients handle this for
you — each retry creates a fresh session (new cookie, new CAPTCHA image) before
calling your solver again. You never manage this manually; it's why a ~60% solver
still gets you through within the default three attempts.

## See also

- [Installation](../start/installation.md) — the `[ocr]`, `[onnx]`, and `[all]` extras.
- [CAPTCHA reference](../reference/captcha.md) — full API for the solver classes.
- [High Courts guide](high-courts.md) and [District Courts guide](district-courts.md) — the CAPTCHA-gated live clients in context.
