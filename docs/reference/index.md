# API Reference

Auto-generated from the source docstrings. This is the canonical, always-in-sync
reference for the `bharat_courts` package — every signature, parameter and return
type below is extracted directly from the code.

New to the library? Start with the [Quickstart](../start/quickstart.md) and the
[guides](../guides/facade.md), which show these APIs in context.

<div class="grid cards" markdown>

-   :material-magnify-scan:{ .lg .middle } __[Judgments facade](facade.md)__

    ---

    `Judgments` — the federated entry point. One `find()` call, routed to the
    right backend automatically.

-   :material-server-network:{ .lg .middle } __[Live clients](clients.md)__

    ---

    `HCServicesClient`, `DistrictCourtClient`, `JudgmentSearchClient`,
    `CalcuttaHCClient`, `SCIClient` — the portal scrapers.

-   :material-database-search:{ .lg .middle } __[Archive client](archive.md)__

    ---

    `ArchiveClient` — DuckDB queries over the AWS Open Data buckets, plus PDF
    retrieval and caching.

-   :material-shape:{ .lg .middle } __[Data models](models.md)__

    ---

    `Judgment`, `CaseInfo`, `CaseOrder`, `CauseListPDF`, `SearchResult` and the
    rest of the typed DTOs.

-   :material-bank:{ .lg .middle } __[Courts registry](courts.md)__

    ---

    `get_court`, `infer_court_from_cnr` and the static registry of every
    supported court.

-   :material-robot:{ .lg .middle } __[CAPTCHA solvers](captcha.md)__

    ---

    The pluggable `CaptchaSolver` ABC and its OCR / ONNX / manual
    implementations.

</div>
