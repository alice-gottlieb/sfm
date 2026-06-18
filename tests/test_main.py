from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import main


def test_parse_ticket_date_accepts_iso_date():
    assert main.parse_ticket_date("2026-06-18") == "2026-06-18"


def test_parse_ticket_date_rejects_invalid_format():
    with pytest.raises(RuntimeError, match="YYYY-MM-DD"):
        main.parse_ticket_date("06/18/2026")


def test_resolve_credentials_prefers_explicit_path(tmp_path):
    explicit = tmp_path / "explicit.json"
    result = main.resolve_credentials_path(
        explicit,
        environ={"SFM_KEYS_PATH": str(tmp_path / "env.json")},
        cwd=tmp_path,
        home=tmp_path,
    )
    assert result == explicit


def test_resolve_credentials_precedence(tmp_path):
    env_path = tmp_path / "env.json"
    local_path = tmp_path / "KEYS.txt"
    config_path = tmp_path / ".config" / "sfm" / "KEYS.json"
    local_path.write_text("{}")
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{}")

    assert main.resolve_credentials_path(
        None,
        environ={"SFM_KEYS_PATH": str(env_path)},
        cwd=tmp_path,
        home=tmp_path,
    ) == env_path
    assert main.resolve_credentials_path(
        None, environ={}, cwd=tmp_path, home=tmp_path
    ) == local_path

    local_path.unlink()
    assert main.resolve_credentials_path(
        None, environ={}, cwd=tmp_path, home=tmp_path
    ) == config_path


def test_resolve_credentials_reports_all_fallbacks(tmp_path):
    with pytest.raises(RuntimeError, match="SFM_KEYS_PATH"):
        main.resolve_credentials_path(
            None, environ={}, cwd=tmp_path, home=tmp_path
        )


def test_load_credentials_rejects_malformed_file(tmp_path):
    keys_path = tmp_path / "keys.json"
    keys_path.write_text("not-json")
    with pytest.raises(RuntimeError, match="Could not parse"):
        main.load_credentials(keys_path)


def test_ticket_count_cli_allows_only_one_or_two():
    assert main.parse_args(["-n", "1"]).num_tickets == 1
    assert main.parse_args(["-n", "2"]).num_tickets == 2
    with pytest.raises(SystemExit):
        main.parse_args(["-n", "3"])


def test_special_mode_fails_before_firefox_starts(capsys):
    args = main.parse_args(["--special"])
    with patch("main.build_driver") as build_driver:
        assert main.run(args) == 1
    build_driver.assert_not_called()
    assert "under development" in capsys.readouterr().err


def test_normal_mode_no_does_not_submit(tmp_path):
    driver = MagicMock()
    wait = MagicMock()
    screenshot = tmp_path / "purchase.png"
    with (
        patch("main.open_png_with_system_viewer") as viewer,
        patch("main.confirm_purchase_prompt", return_value=False) as prompt,
        patch("main.submit_purchase_with_diagnostics") as submit,
    ):
        main.finish_general_admission_order(
            driver, wait, tmp_path, screenshot, auto=False
        )

    viewer.assert_called_once_with(screenshot)
    prompt.assert_called_once_with()
    submit.assert_not_called()


def test_normal_mode_yes_submits_with_intermediate_images(tmp_path):
    driver = MagicMock()
    wait = MagicMock()
    screenshot = tmp_path / "purchase.png"
    with (
        patch("main.open_png_with_system_viewer"),
        patch("main.confirm_purchase_prompt", return_value=True),
        patch("main.submit_purchase_with_diagnostics") as submit,
    ):
        main.finish_general_admission_order(
            driver, wait, tmp_path, screenshot, auto=False
        )

    submit.assert_called_once_with(
        driver, wait, tmp_path, show_intermediate=True
    )


def test_auto_mode_skips_prompt_and_intermediate_viewer(tmp_path):
    driver = MagicMock()
    wait = MagicMock()
    screenshot = tmp_path / "purchase.png"
    with (
        patch("main.open_png_with_system_viewer") as viewer,
        patch("main.confirm_purchase_prompt") as prompt,
        patch("main.submit_purchase_with_diagnostics") as submit,
    ):
        main.finish_general_admission_order(
            driver, wait, tmp_path, screenshot, auto=True
        )

    viewer.assert_not_called()
    prompt.assert_not_called()
    submit.assert_called_once_with(
        driver, wait, tmp_path, show_intermediate=False
    )


def test_member_allotment_error_is_clear(tmp_path):
    driver = MagicMock()
    wait = MagicMock()
    with patch(
        "main.summarize_page",
        return_value="Member Free Not Available\nalready booked your daily allotment",
    ):
        with pytest.raises(RuntimeError, match="daily member-ticket allotment"):
            main.select_general_admission_tickets(
                driver, wait, tmp_path, ticket_count=1, auto=False
            )

    wait.until.assert_not_called()


def test_submit_purchase_checks_terms_and_clicks_both_proceed_buttons(tmp_path):
    driver = MagicMock()
    driver.page_source = "<html>final confirmation</html>"
    wait = MagicMock()
    accept_terms = MagicMock()
    accept_terms.is_selected.return_value = False
    wait.until.side_effect = [accept_terms, True]
    payment_path = tmp_path / "payment.png"
    confirmation_path = tmp_path / "confirmation.png"

    with (
        patch("main.dismiss_cookie_banner"),
        patch("main.click_purchase_proceed") as proceed,
        patch(
            "main.save_page_result",
            side_effect=[payment_path, confirmation_path],
        ),
        patch("main.open_png_with_system_viewer") as viewer,
    ):
        main.submit_purchase(
            driver, wait, tmp_path, show_intermediate=False
        )

    assert proceed.call_count == 2
    assert call("arguments[0].click();", accept_terms) in driver.execute_script.call_args_list
    viewer.assert_called_once_with(confirmation_path)


def test_checkout_failure_saves_diagnostic_without_retry(tmp_path):
    driver = MagicMock()
    wait = MagicMock()
    with (
        patch("main.submit_purchase", side_effect=RuntimeError("failed")) as submit,
        patch("main.save_page_result") as save_result,
    ):
        with pytest.raises(RuntimeError, match="No automatic retry"):
            main.submit_purchase_with_diagnostics(
                driver, wait, tmp_path, show_intermediate=False
            )

    submit.assert_called_once_with(driver, wait, tmp_path, False)
    save_result.assert_called_once_with(driver, tmp_path, "checkout-failure")


def test_default_output_dir_uses_private_user_data_locations(tmp_path):
    assert main.default_output_dir("Darwin", {}, tmp_path) == (
        tmp_path / "Library" / "Application Support" / "sfm" / "artifacts"
    )
    assert main.default_output_dir("Linux", {}, tmp_path) == (
        tmp_path / ".local" / "share" / "sfm" / "artifacts"
    )
    assert main.default_output_dir(
        "Windows", {"LOCALAPPDATA": str(tmp_path / "Local")}, tmp_path
    ) == (tmp_path / "Local" / "sfm" / "artifacts")
