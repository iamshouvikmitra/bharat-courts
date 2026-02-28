"""Shared test fixtures for bharat-courts."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def hcservices_case_status_html():
    return (FIXTURES_DIR / "hcservices_case_status.html").read_text()


@pytest.fixture
def hcservices_orders_html():
    return (FIXTURES_DIR / "hcservices_orders.html").read_text()


@pytest.fixture
def hcservices_cause_list_html():
    return (FIXTURES_DIR / "hcservices_cause_list.html").read_text()


@pytest.fixture
def hcservices_case_status_json():
    return (FIXTURES_DIR / "hcservices_case_status.json").read_text()


@pytest.fixture
def judgments_search_html():
    return (FIXTURES_DIR / "judgments_search.html").read_text()
