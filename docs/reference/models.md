# Data models

Every result type is a plain dataclass with a `to_dict()` / `to_json()` mixin, so
results serialise straight to JSON for spreadsheets, dashboards or case-management
tools.

::: bharat_courts.models
    options:
      members:
        - Judgment
        - JudgmentResult
        - CaseInfo
        - CaseOrder
        - CauseListPDF
        - CauseListEntry
        - SearchResult
        - Court
        - CourtType
