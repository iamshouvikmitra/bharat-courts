"""Tests for District Courts client using respx mocks."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import respx
from httpx import Response

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.districtcourts.client import DistrictCourtClient
from bharat_courts.districtcourts.endpoints import BASE_URL, CAPTCHA_IMAGE_URL

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class AutoCaptchaSolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        return "test123"


@pytest.fixture
def fast_config():
    return BharatCourtsConfig(request_delay=0, timeout=5, max_retries=1)


@pytest.fixture
def captcha_solver():
    return AutoCaptchaSolver()


def _ajax_response(*, status=1, app_token="tok_new", **kwargs):
    """Build a mock AJAX response."""
    data = {"status": status, "app_token": app_token, **kwargs}
    return Response(200, text=json.dumps(data))


def _mock_session_init():
    """Set up mocks for session initialization (GET base + getCaptcha)."""
    respx.get(url__startswith=BASE_URL).mock(return_value=Response(200, text="<html></html>"))
    respx.get(url__startswith=CAPTCHA_IMAGE_URL).mock(
        return_value=Response(200, content=b"fake_captcha_image")
    )


@pytest.mark.asyncio
async def test_list_districts(fast_config, captcha_solver):
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()

    with respx.mock:
        _mock_session_init()
        # getCaptcha (init)
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        # fillDistrict
        respx.post(url__regex=r".*fillDistrict").mock(
            return_value=_ajax_response(dist_list=districts_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            districts = await client.list_districts("8")

    assert len(districts) == 5
    assert districts["1"] == "Patna"
    assert districts["24"] == "Araria"


@pytest.mark.asyncio
async def test_list_complexes(fast_config, captcha_solver):
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    complexes_html = (FIXTURES_DIR / "districtcourts_complexes.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(
            return_value=_ajax_response(dist_list=districts_html)
        )
        respx.post(url__regex=r".*fillcomplex").mock(
            return_value=_ajax_response(complex_list=complexes_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            complexes = await client.list_complexes("8", "1")

    assert len(complexes) == 3
    assert "1080010@2,3,4@Y" in complexes
    assert complexes["1080010@2,3,4@Y"] == "Civil Court, Patna Sadar"


@pytest.mark.asyncio
async def test_case_status(fast_config, captcha_solver):
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitCaseNo").mock(
            return_value=_ajax_response(case_data=case_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                est_code="2",
                case_type="1",
                case_number="123",
                year="2024",
            )

    assert len(results) == 3
    assert results[0].case_number == "CS/123/2024"
    assert results[0].petitioner == "Ram Kumar Singh"
    assert results[0].cnr_number == "BHAR010001232024"


@pytest.mark.asyncio
async def test_case_status_by_party(fast_config, captcha_solver):
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitPartyName").mock(
            return_value=_ajax_response(party_data=case_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status_by_party(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                party_name="Ram Kumar",
                year="2024",
            )

    assert len(results) == 3
    assert results[0].petitioner == "Ram Kumar Singh"


@pytest.mark.asyncio
async def test_court_orders(fast_config, captcha_solver):
    orders_html = (FIXTURES_DIR / "districtcourts_court_orders.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*courtorder/submitCaseNo").mock(
            return_value=_ajax_response(order_data=orders_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.court_orders(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                case_type="1",
                case_number="123",
                year="2024",
            )

    assert len(results) == 2
    assert results[0].order_type == "Interim Order"
    assert "display_pdf.php" in results[0].pdf_url


@pytest.mark.asyncio
async def test_captcha_retry(fast_config, captcha_solver):
    """Test that CAPTCHA retry creates fresh sessions."""
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()
    call_count = {"submitCaseNo": 0}

    def submit_side_effect(request):
        call_count["submitCaseNo"] += 1
        if call_count["submitCaseNo"] == 1:
            # First attempt: CAPTCHA failure
            return Response(
                200, text=json.dumps({"status": 0, "app_token": "tok2", "div_captcha": "<img>"})
            )
        # Second attempt: success
        return Response(
            200, text=json.dumps({"status": 1, "app_token": "tok3", "case_data": case_html})
        )

    fast_config_retry = BharatCourtsConfig(request_delay=0, timeout=5, max_retries=1)

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitCaseNo").mock(side_effect=submit_side_effect)

        async with DistrictCourtClient(
            config=fast_config_retry, captcha_solver=captcha_solver
        ) as client:
            results = await client.case_status(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                case_type="1",
                case_number="123",
                year="2024",
                # Allow enough retries
            )

    assert len(results) == 3
    assert call_count["submitCaseNo"] == 2


@pytest.mark.asyncio
async def test_app_token_rotation(fast_config, captcha_solver):
    """Verify that app_token from responses is used in subsequent requests."""
    captured_tokens = []

    def capture_token(request):
        body = request.content.decode()
        for part in body.split("&"):
            if part.startswith("app_token="):
                captured_tokens.append(part.split("=", 1)[1])
        return Response(
            200,
            text=json.dumps(
                {
                    "status": 1,
                    "app_token": f"tok_{len(captured_tokens)}",
                    "dist_list": '<option value="1">Patna</option>',
                }
            ),
        )

    with respx.mock:
        _mock_session_init()
        respx.post(url__startswith=BASE_URL).mock(side_effect=capture_token)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            await client.list_districts("8")

    # First call (getCaptcha) should have empty token, subsequent should have rotated tokens
    assert captured_tokens[0] == ""  # Initial empty token
    # After getCaptcha returns tok_1, next call should use it
    assert captured_tokens[1] == "tok_1"


@pytest.mark.asyncio
async def test_bundled_state_snapshot():
    """The offline DISTRICT_STATES snapshot must carry the codes verified
    against the live portal on 2026-08-23 (#25 — 13 of 36 had drifted,
    with Delhi's old code "7" actually meaning Jharkhand)."""
    from bharat_courts.districtcourts.endpoints import DISTRICT_STATES

    assert len(DISTRICT_STATES) == 36
    assert DISTRICT_STATES["Bihar"] == "8"
    assert DISTRICT_STATES["Delhi"] == "26"
    assert DISTRICT_STATES["Jharkhand"] == "7"
    assert DISTRICT_STATES["Maharashtra"] == "1"
    assert DISTRICT_STATES["Haryana"] == "14"
    assert DISTRICT_STATES["Tamil Nadu"] == "10"


# Regression tests for the field-name + court-name fixes (issue #3) ---------


def test_case_status_form_sends_both_case_no_aliases():
    """The portal's submitCaseNo() JS appends `case_no` *in addition* to
    the form-serialized `search_case_no`. The server validates against
    `case_no` — sending only `search_case_no` triggers a "Case Number is
    required" error. Lock in that we send both."""
    from bharat_courts.districtcourts.endpoints import case_status_by_number_form

    form = case_status_by_number_form(
        state_code="8",
        dist_code="1",
        court_complex_code="1080010",
        est_code="2",
        case_type="89^2",
        case_number="42",
        year="2024",
        captcha="abc123",
    )
    assert form["search_case_no"] == "42"
    assert form["case_no"] == "42"
    assert form["case_captcha_code"] == "abc123"
    assert form["rgyear"] == "2024"


def test_court_orders_form_sends_aliases():
    """courtorder/submitCaseNo JS appends `case_no`, `rgyear`, `radvalue`
    in addition to the form's `search_case_no`, `rgyearCaseOrder`, `frad`."""
    from bharat_courts.districtcourts.endpoints import court_orders_by_number_form

    form = court_orders_by_number_form(
        state_code="8",
        dist_code="1",
        court_complex_code="1080010",
        est_code="2",
        case_type="89^2",
        case_number="42",
        year="2024",
        captcha="abc123",
        order_type="both",
    )
    assert form["search_case_no"] == form["case_no"] == "42"
    assert form["rgyearCaseOrder"] == form["rgyear"] == "2024"
    assert form["frad"] == form["radvalue"] == "both"


def test_cause_list_form_requires_non_empty_court_name():
    """The portal's submit_causelist() JS appends `court_name_txt`=
    selected option text. Server rejects empty `court_name_txt` with
    "Court Name is required". The form builder now requires both
    `court_no` and `court_name`."""
    from bharat_courts.districtcourts.endpoints import cause_list_form

    form = cause_list_form(
        state_code="8",
        dist_code="1",
        court_complex_code="1080010",
        est_code="2",
        court_no="2^1",
        court_name="District & Sessions Judge",
        causelist_date="01-04-2026",
        civil=True,
        captcha="abc123",
    )
    assert form["CL_court_no"] == "2^1"
    assert form["court_name_txt"] == "District & Sessions Judge"
    assert form["cicri"] == "civ"

    # Default-empty `court_name` must NOT be accepted by the public client
    # method (it auto-resolves it via list_cause_list_courts), but the
    # form-builder itself accepts whatever is passed; that's fine — the
    # higher-level client guard is the policy gate.
    with pytest.raises(TypeError):
        # court_name is required as kwarg now (no default)
        cause_list_form(
            state_code="8",
            dist_code="1",
            court_complex_code="1080010",
            est_code="2",
            court_no="2^1",
            causelist_date="01-04-2026",
            civil=True,
            captcha="abc123",
        )


@pytest.mark.asyncio
async def test_list_cause_list_courts_parses_dropdown(fast_config, captcha_solver):
    """list_cause_list_courts hits cause_list/fillCauseList and parses the
    HTML option fragment in the `cause_list` JSON field."""
    cause_list_html = (
        '<option value="">Select court</option>'
        '<option value="2^1">1-Sri Rupesh Deo-Principal District &amp; Sessions Judge</option>'
        '<option value="2^2">2-Sri Sunil Dutta Pandey-Principal Judge</option>'
    )

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=rf"^{BASE_URL}/.*p=cause_list/fillCauseList").mock(
            return_value=_ajax_response(cause_list=cause_list_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            mapping = await client.list_cause_list_courts("8", "1", "1080010", "2")

    assert mapping["2^1"].startswith("1-Sri Rupesh Deo")
    assert mapping["2^2"].startswith("2-Sri Sunil Dutta Pandey")
    assert "" not in mapping  # empty placeholder filtered


@pytest.mark.asyncio
async def test_cause_list_auto_resolves_court_name(fast_config, captcha_solver):
    """When court_name is not given, cause_list calls list_cause_list_courts
    once and looks up the matching name. Verify the captured submit body
    carries the resolved name in court_name_txt."""
    cause_list_html = (
        '<option value="2^1">1-Sri Rupesh Deo-Principal District &amp; Sessions Judge</option>'
    )
    captured_body: dict = {}

    def capture_submit(request):
        captured_body["body"] = request.content.decode()
        return _ajax_response(causelist_data="")

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=rf"^{BASE_URL}/.*p=cause_list/fillCauseList").mock(
            return_value=_ajax_response(cause_list=cause_list_html)
        )
        respx.post(url__regex=rf"^{BASE_URL}/.*p=cause_list/submitCauseList").mock(
            side_effect=capture_submit
        )
        # set_data + non-fillCauseList AJAXs
        respx.post(url__regex=rf"^{BASE_URL}/.*p=casestatus/set_data").mock(
            return_value=_ajax_response()
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            await client.cause_list(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                est_code="2",
                court_no="2^1",
                causelist_date="01-04-2026",
                civil=True,
            )

    assert "court_name_txt=" in captured_body["body"]
    # BeautifulSoup would have unescaped &amp; → & before storing.
    assert "Principal+District+%26+Sessions+Judge" in captured_body["body"]


@pytest.mark.asyncio
async def test_cause_list_raises_on_unknown_court_no(fast_config, captcha_solver):
    """If court_no doesn't appear in the dropdown list, raise ValueError
    rather than silently sending a blank court_name to the portal."""
    cause_list_html = '<option value="2^1">A Real Court</option>'

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=rf"^{BASE_URL}/.*p=cause_list/fillCauseList").mock(
            return_value=_ajax_response(cause_list=cause_list_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            with pytest.raises(ValueError, match="not found in fillCauseList"):
                await client.cause_list(
                    state_code="8",
                    dist_code="1",
                    court_complex_code="1080010",
                    est_code="2",
                    court_no="9^9",
                    civil=True,
                )


# ------------------------------------------------------------------
# Anti-bot "delimeter" header (portal change ~2026-07-22)
# ------------------------------------------------------------------

#: Minimal stand-ins for the portal's homepage + components.js.
_HOME_HTML = '<html><script src="/ecourtindia_v6/js/components.js?v=1784899796"></script></html>'


def _components_js(delimeter: str, companion: str = "Xgy786trbsd7y") -> str:
    """Stand-in for the portal's components.js, in its current shape: the
    secret plus a headers block naming which headers carry it."""
    return (
        "function ajaxCall(jsonobj)\n{\n"
        f'\tvar delimeter="{delimeter}";\n'
        "\t$.ajax({\n"
        "\t\theaders: {\n"
        '\t\t\t"delimeter": delimeter,\n'
        f'\t\t\t"{companion}":delimeter\n'
        "\t\t},\n"
        "\t});\n}"
    )


def _mock_session_init_with_delimeter(delimeter: str):
    """Session init where components.js serves a real rotating secret."""
    respx.get(url__regex=r".*js/components\.js.*").mock(
        return_value=Response(200, text=_components_js(delimeter))
    )
    respx.get(url__startswith=CAPTCHA_IMAGE_URL).mock(
        return_value=Response(200, content=b"fake_captcha_image")
    )
    respx.get(url__startswith=BASE_URL).mock(return_value=Response(200, text=_HOME_HTML))


@pytest.mark.asyncio
async def test_ajax_posts_carry_scraped_delimeter_headers(fast_config, captcha_solver):
    """Every AJAX POST must carry the secret scraped from components.js under
    *every* header name that block names — without them the portal rejects
    everything, including the CAPTCHA-free dropdowns."""
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    seen = []

    def _capture(request):
        seen.append(dict(request.headers))
        return _ajax_response(dist_list=districts_html)

    with respx.mock:
        _mock_session_init_with_delimeter("73vmgasjxcminndsf846Pq")
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(side_effect=_capture)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            await client.list_districts("8")

    assert seen, "fillDistrict was never called"
    assert seen[0]["delimeter"] == "73vmgasjxcminndsf846Pq"
    assert seen[0]["xgy786trbsd7y"] == "73vmgasjxcminndsf846Pq"
    assert "abc" not in seen[0], "the pre-2026-08-04 decoy must no longer be sent"


@pytest.mark.asyncio
async def test_rotated_delimeter_is_rescraped_and_request_retried(fast_config, captcha_solver):
    """The secret rotates roughly hourly. If it turns over mid-session the
    portal answers 'Invalid Request'; the client must re-scrape and replay
    the request rather than failing the query."""
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    invalid = Response(
        200,
        text=json.dumps(
            {
                "errormsg": "<strong>Oops!</strong>There is something wrong.....!!!, "
                "Invalid Request...!Try once again",
                "app_token": "",
            }
        ),
    )
    attempts = []

    def _fill_district(request):
        attempts.append(request.headers.get("delimeter"))
        # Only the freshly-rotated secret is accepted.
        if request.headers.get("delimeter") == "NEWSECRET":
            return _ajax_response(dist_list=districts_html)
        return invalid

    with respx.mock:
        respx.get(url__startswith=CAPTCHA_IMAGE_URL).mock(
            return_value=Response(200, content=b"fake_captcha_image")
        )
        # components.js serves the stale value first, then rotates.
        respx.get(url__regex=r".*js/components\.js.*").mock(
            side_effect=[
                Response(200, text=_components_js("STALESECRET")),
                Response(200, text=_components_js("NEWSECRET")),
            ]
        )
        respx.get(url__startswith=BASE_URL).mock(return_value=Response(200, text=_HOME_HTML))
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(side_effect=_fill_district)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            districts = await client.list_districts("8")

    assert attempts == ["STALESECRET", "NEWSECRET"], attempts
    assert districts["1"] == "Patna"


@pytest.mark.asyncio
async def test_renamed_companion_header_is_rescraped_and_request_retried(
    fast_config, captcha_solver
):
    """Regression for #17: the portal renames the companion header, not just
    the secret. A rejection must re-scrape the *names* too, otherwise the whole
    backend stays broken until someone edits a constant."""
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    invalid = Response(
        200,
        text=json.dumps(
            {
                "errormsg": "<strong>Oops!</strong>There is something wrong..!!!, "
                "Invalid Request...!! Try once again",
                "app_token": "",
            }
        ),
    )
    attempts = []

    def _fill_district(request):
        attempts.append(sorted(h for h in request.headers if h.startswith(("delimeter", "x"))))
        # The secret never changes here — only the header carrying it does.
        if request.headers.get("brandNewName") == "SAMESECRET":
            return _ajax_response(dist_list=districts_html)
        return invalid

    with respx.mock:
        respx.get(url__startswith=CAPTCHA_IMAGE_URL).mock(
            return_value=Response(200, content=b"fake_captcha_image")
        )
        respx.get(url__regex=r".*js/components\.js.*").mock(
            side_effect=[
                Response(200, text=_components_js("SAMESECRET", companion="oldName")),
                Response(200, text=_components_js("SAMESECRET", companion="brandNewName")),
            ]
        )
        respx.get(url__startswith=BASE_URL).mock(return_value=Response(200, text=_HOME_HTML))
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(side_effect=_fill_district)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            districts = await client.list_districts("8")

    assert len(attempts) == 2, attempts
    assert districts["1"] == "Patna"


@pytest.mark.asyncio
async def test_invalid_request_not_retried_when_delimeter_unchanged(fast_config, captcha_solver):
    """If re-scraping yields the same secret the rejection is about something
    else — surface it instead of silently replaying the request forever."""
    from bharat_courts.districtcourts.parser import InvalidRequestError

    invalid = Response(
        200, text=json.dumps({"errormsg": "Invalid Request...!Try once again", "app_token": ""})
    )
    calls = []

    def _fill_district(request):
        calls.append(1)
        return invalid

    with respx.mock:
        _mock_session_init_with_delimeter("SAMESECRET")
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(side_effect=_fill_district)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            with pytest.raises(InvalidRequestError):
                await client.list_districts("8")

    assert len(calls) == 1, "should not retry when the secret did not rotate"


# ------------------------------------------------------------------
# CNR lookup
# ------------------------------------------------------------------


def test_cnr_form():
    from bharat_courts.districtcourts import endpoints as dc_endpoints

    form = dc_endpoints.case_status_by_cnr_form(cnr="gjrj060015282018", captcha="abc123")
    # the district portal names the captcha field differently from HC
    assert form == {"cino": "GJRJ060015282018", "fcaptcha_code": "abc123"}


@pytest.mark.parametrize("bad", ["", "GJRJ06001528201", "GJRJ0600152820188", "GJRJ0600152820!8"])
async def test_cnr_lookup_rejects_malformed(bad):
    from bharat_courts import DistrictCourtClient

    client = DistrictCourtClient()
    with pytest.raises(ValueError, match="16 alphanumeric"):
        await client.case_status_by_cnr(bad)


# ------------------------------------------------------------------
# Empty / non-JSON responses are retried, never "0 results" (#26)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_response_is_retried_then_succeeds(fast_config, captcha_solver):
    """The portal fairly often answers submitPartyName with a plain empty
    string. That used to sail through as a fabricated empty-success dict and
    come out as "0 matching cases" (#26) — it must retry instead."""
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        submit = respx.post(url__regex=r".*submitPartyName").mock(
            side_effect=[
                Response(200, text=""),  # transient portal blip
                _ajax_response(party_data=case_html),
            ]
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status_by_party(
                state_code="26",
                dist_code="8",
                court_complex_code="1260008@5,6,7@N",
                party_name="Bank",
                year="2023",
            )

    assert submit.call_count == 2
    assert len(results) == 3, "the retry's real results must come through"


@pytest.mark.asyncio
async def test_persistent_empty_response_raises_not_zero_results(fast_config, captcha_solver):
    from bharat_courts.districtcourts.parser import MalformedResponseError

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitPartyName").mock(return_value=Response(200, text=""))

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            with pytest.raises(MalformedResponseError):
                await client.case_status_by_party(
                    state_code="26",
                    dist_code="8",
                    court_complex_code="1260008@5,6,7@N",
                    party_name="Bank",
                    year="2023",
                )


# ------------------------------------------------------------------
# list_states scrapes the live dropdown (#25)
# ------------------------------------------------------------------

_STATE_PAGE = """
<html><body>
<select name='sess_state_code' id='sess_state_code'>
<option value='0'>Select state</option>
<option value='26'  >Delhi</option>
<option value='1'  >Maharashtra</option>
</select>
</body></html>
"""


@pytest.mark.asyncio
async def test_list_states_scrapes_live_dropdown(fast_config, captcha_solver):
    with respx.mock:
        respx.get(url__regex=r".*casestatus/index").mock(
            return_value=Response(200, text=_STATE_PAGE)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            states = await client.list_states()

    assert states == {"26": "Delhi", "1": "Maharashtra"}


@pytest.mark.asyncio
async def test_list_states_falls_back_to_snapshot(fast_config, captcha_solver):
    """If the page can't be fetched, the bundled snapshot still answers —
    and it must carry the corrected codes (#25: Delhi is 26, not 7)."""
    with respx.mock:
        respx.get(url__regex=r".*casestatus/index").mock(return_value=Response(503, text="down"))

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            states = await client.list_states()

    assert states["26"] == "Delhi"
    assert states["7"] == "Jharkhand"
    assert states["1"] == "Maharashtra"
    assert states["10"] == "Tamil Nadu"


# ------------------------------------------------------------------
# Complex codes are reduced to the bare form the server expects (#26/#28)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_dropdown_complex_value_is_normalised(fast_config, captcha_solver):
    """list_complexes keys look like "1260008@5,6,7@N". The portal's own JS
    splits off the @-suffix before submitting; sending it unsplit makes the
    server answer with an empty body. Passing the dropdown value through
    must put only the bare code on the wire."""
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        set_data = respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        submit = respx.post(url__regex=r".*submitPartyName").mock(
            return_value=_ajax_response(party_data=case_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status_by_party(
                state_code="26",
                dist_code="8",
                court_complex_code="1260008@5,6,7@N",
                party_name="Bank",
                year="2023",
            )

    assert len(results) == 3
    submit_body = submit.calls.last.request.content.decode()
    assert (
        "court_complex_code=1260008&" in submit_body
        or submit_body.endswith("court_complex_code=1260008")
        or "court_complex_code=1260008" in submit_body
    )
    assert "%405%2C6%2C7%40N" not in submit_body, "@-suffix must not reach the wire"
    set_body = set_data.calls.last.request.content.decode()
    assert "court_complex_code=1260008" in set_body
    assert "%40" not in set_body.split("court_complex_code=")[1].split("&")[0]


# ------------------------------------------------------------------
# Act search
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_acts(fast_config, captcha_solver):
    options = (
        '<option value="">Select Act Type</option>'
        '<option value="18">Negotiable Instruments Act</option>'
        '<option value="523">Bharatiya Nyaya Sanhita</option>'
    )

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        route = respx.post(url__regex=r".*fillActType").mock(
            return_value=_ajax_response(act_list=options)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            acts = await client.list_acts("26", "1", "1260001@1,2,3,4@Y", est_code="2")

    assert acts == {"18": "Negotiable Instruments Act", "523": "Bharatiya Nyaya Sanhita"}
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["court_complex_code"] == ["1260001"]
    assert body["est_code"] == ["2"]


@pytest.mark.asyncio
async def test_case_status_by_act(fast_config, captcha_solver):
    act_html = (FIXTURES_DIR / "districtcourts_act_search.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        route = respx.post(url__regex=r".*submitAct").mock(
            return_value=_ajax_response(act_data=act_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status_by_act(
                state_code="26",
                dist_code="1",
                court_complex_code="1260001",
                est_code="1",
                act_code="18",
                section="138",
            )

    body = parse_qs(route.calls[0].request.content.decode())
    assert body["actcode"] == ["18"]
    assert body["under_sec"] == ["138"]
    assert body["case_status"] == ["Pending"]
    assert body["act_captcha_code"] == ["test123"]
    assert len(results) == 23
    assert results[0].cnr_number == "DLNE010023672026"
    assert all(r.status == "Pending" for r in results)


@pytest.mark.asyncio
async def test_case_status_by_act_rejects_long_section(fast_config, captcha_solver):
    """The district form caps under_sec at 15, tighter than the HC form's 100."""
    with respx.mock(assert_all_called=False) as mock:
        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            with pytest.raises(ValueError, match="at most 15"):
                await client.case_status_by_act(
                    state_code="26",
                    dist_code="1",
                    court_complex_code="1260001",
                    act_code="18",
                    section="1" * 16,
                )

    assert mock.calls.call_count == 0
