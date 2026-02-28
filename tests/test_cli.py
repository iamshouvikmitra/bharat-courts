"""Tests for CLI commands."""

from click.testing import CliRunner

from bharat_courts.cli import main


def test_courts_command():
    runner = CliRunner()
    result = runner.invoke(main, ["courts"])
    assert result.exit_code == 0
    assert "Delhi" in result.output
    assert "Supreme Court" in result.output


def test_courts_hc_filter():
    runner = CliRunner()
    result = runner.invoke(main, ["courts", "--type", "hc"])
    assert result.exit_code == 0
    assert "Delhi" in result.output
    # Supreme Court should not appear with HC filter
    assert "Supreme Court of India" not in result.output


def test_courts_sc_filter():
    runner = CliRunner()
    result = runner.invoke(main, ["courts", "--type", "sc"])
    assert result.exit_code == 0
    assert "Supreme Court" in result.output


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_search_unknown_court():
    runner = CliRunner()
    result = runner.invoke(
        main, ["search", "nonexistent", "--case-type", "WP", "--case-number", "1", "--year", "2024"]
    )
    assert result.exit_code == 1
    assert "Unknown court" in result.output
