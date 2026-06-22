# Courts registry

The static registry of every supported court and the helpers for resolving them
by code, name, eCourts state code, or CNR prefix.

::: bharat_courts.courts
    options:
      members:
        - get_court
        - get_court_by_name
        - get_court_by_state_code
        - infer_court_from_cnr
        - list_all_courts
        - list_high_courts
        - ALL_COURTS
        - SUPREME_COURT
