from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from selenium.common.exceptions import TimeoutException

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


def test_special_cli_uses_default_or_explicit_exhibition():
    assert main.parse_args(["--special"]).special == main.DEFAULT_SPECIAL_ADMISSION
    assert main.parse_args(["-s", "Other Exhibition"]).special == "Other Exhibition"


def test_time_cli_accepts_short_and_long_flags():
    assert main.parse_args(["-s", "-t", "12:00 pm"]).time == "12:00 pm"
    assert main.parse_args(["--special", "--time", "1:30 PM"]).time == "1:30 PM"


@pytest.mark.parametrize(
    ("raw_time", "site_time"),
    [
        ("12:00 pm", "12:00 p.m."),
        ("1:30 PM", "1:30 p.m."),
        ("09:05 a.m.", "9:05 a.m."),
    ],
)
def test_normalize_ticket_time_matches_site_format(raw_time, site_time):
    assert main.normalize_ticket_time(raw_time) == site_time


def test_normalize_ticket_time_rejects_non_12_hour_input():
    with pytest.raises(RuntimeError, match="12-hour format"):
        main.normalize_ticket_time("13:00")


def test_time_requires_special_before_firefox_starts(capsys):
    args = main.parse_args(["--time", "12:00 pm"])
    with patch("main.build_driver") as build_driver:
        assert main.run(args) == 1
    build_driver.assert_not_called()
    assert "--time requires --special" in capsys.readouterr().err


def test_special_mode_prompts_for_and_selects_time(tmp_path):
    args = main.parse_args(
        ["2026-06-18", "--special", "--keys", str(tmp_path / "keys.json")]
    )
    driver = MagicMock()
    wait = MagicMock()
    with (
        patch("main.resolve_credentials_path", return_value=tmp_path / "keys.json"),
        patch("main.load_credentials", return_value=("member@example.com", "secret")),
        patch("main.build_driver", return_value=driver),
        patch("main.log_in", return_value=wait),
        patch("main.open_performance_page") as open_performance,
        patch("main.select_admission") as select_admission,
        patch(
            "main.prompt_for_special_exhibition_time",
            return_value="12:30 pm",
        ) as prompt_for_time,
        patch("main.select_special_exhibition_time") as select_time,
        patch("main.select_general_admission_tickets") as select_tickets,
    ):
        assert main.run(args) == 0

    open_performance.assert_called_once_with(
        driver, wait, main.default_output_dir(), "2026-06-18"
    )
    select_admission.assert_called_once_with(
        driver,
        wait,
        main.default_output_dir(),
        main.DEFAULT_SPECIAL_ADMISSION,
        is_special=True,
    )
    prompt_for_time.assert_called_once_with(driver)
    select_time.assert_called_once_with(
        driver, wait, main.default_output_dir(), "12:30 pm"
    )
    select_tickets.assert_called_once_with(
        driver, wait, main.default_output_dir(), 1, False
    )
    driver.quit.assert_called_once_with()


def test_special_mode_selects_requested_time(tmp_path):
    args = main.parse_args(
        [
            "2026-06-18",
            "--special",
            "--time",
            "12:00 pm",
            "--num-tickets",
            "2",
            "--auto",
            "--keys",
            str(tmp_path / "keys.json"),
        ]
    )
    driver = MagicMock()
    wait = MagicMock()
    with (
        patch("main.resolve_credentials_path", return_value=tmp_path / "keys.json"),
        patch("main.load_credentials", return_value=("member@example.com", "secret")),
        patch("main.build_driver", return_value=driver),
        patch("main.log_in", return_value=wait),
        patch("main.open_performance_page"),
        patch("main.select_admission"),
        patch("main.prompt_for_special_exhibition_time") as prompt_for_time,
        patch("main.select_special_exhibition_time") as select_time,
        patch("main.select_general_admission_tickets") as select_tickets,
    ):
        assert main.run(args) == 0

    prompt_for_time.assert_not_called()
    select_time.assert_called_once_with(
        driver, wait, main.default_output_dir(), "12:00 pm"
    )
    select_tickets.assert_called_once_with(
        driver, wait, main.default_output_dir(), 2, True
    )


def test_select_special_exhibition_time_clicks_matching_link(tmp_path):
    driver = MagicMock()
    driver.current_url = "https://tickets.sfmoma.org/tickets/entry"
    time_link = MagicMock()
    wait = MagicMock()
    wait.until.side_effect = [time_link, True]
    clickable_condition = MagicMock()

    with (
        patch("main.dismiss_cookie_banner"),
        patch("main.wait_for_rendered_body"),
        patch("main.save_page_result") as save_result,
        patch(
            "main.EC.element_to_be_clickable",
            return_value=clickable_condition,
        ) as element_to_be_clickable,
    ):
        main.select_special_exhibition_time(
            driver, wait, tmp_path, "12:00 pm"
        )

    locator = element_to_be_clickable.call_args.args[0]
    assert locator[0] == main.By.XPATH
    assert "time-slot--row" in locator[1]
    assert "time-slot-link" in locator[1]
    assert "12:00 p.m." in locator[1]
    assert wait.until.call_args_list[0].args[0] is clickable_condition
    time_link.click.assert_called_once_with()
    save_result.assert_called_once_with(driver, tmp_path, "special-time-result")


def test_prompt_lists_times_and_returns_available_selection(capsys):
    driver = MagicMock()
    noon = MagicMock()
    noon.text = "12:00 p.m."
    twelve_thirty = MagicMock()
    twelve_thirty.text = "12:30 p.m."
    driver.find_elements.return_value = [noon, twelve_thirty]

    with patch("builtins.input", return_value="12:30 pm"):
        assert main.prompt_for_special_exhibition_time(driver) == "12:30 pm"

    output = capsys.readouterr().out
    assert "Available special exhibition entry times:" in output
    assert "12:00 pm" in output
    assert "12:30 pm" in output


def test_prompt_retries_until_available_time_is_entered(capsys):
    driver = MagicMock()
    time_link = MagicMock()
    time_link.text = "12:00 p.m."
    driver.find_elements.return_value = [time_link]

    with patch("builtins.input", side_effect=["13:00", "1:00 pm", "12:00 pm"]):
        assert main.prompt_for_special_exhibition_time(driver) == "12:00 pm"

    output = capsys.readouterr().out
    assert "Invalid time:" in output
    assert "Time is not available: 1:00 pm" in output


def test_prompt_reports_non_interactive_input_failure():
    driver = MagicMock()
    time_link = MagicMock()
    time_link.text = "12:00 p.m."
    driver.find_elements.return_value = [time_link]

    with (
        patch("builtins.input", side_effect=EOFError),
        pytest.raises(RuntimeError, match="Use --time"),
    ):
        main.prompt_for_special_exhibition_time(driver)


def test_special_admission_requires_time_links(tmp_path):
    driver = MagicMock()
    driver.current_url = "https://tickets.sfmoma.org/tickets/performance"
    admission_link = MagicMock()
    admission_link.get_attribute.return_value = "event-type-link"
    wait = MagicMock()
    wait.until.side_effect = [admission_link, True, TimeoutException()]

    with (
        patch("main.dismiss_cookie_banner"),
        patch("main.wait_for_rendered_body"),
        patch("main.save_page_result") as save_result,
    ):
        with pytest.raises(RuntimeError, match="No entry times"):
            main.select_admission(
                driver,
                wait,
                tmp_path,
                main.DEFAULT_SPECIAL_ADMISSION,
                is_special=True,
            )

    admission_link.click.assert_called_once_with()
    save_result.assert_not_called()


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
            main.select_member_ticket_quantity(driver, wait, ticket_count=1)

    wait.until.assert_not_called()


def test_member_quantity_uses_case_insensitive_member_category_xpath():
    driver = MagicMock()
    wait = MagicMock()
    member_select = MagicMock()
    wait.until.return_value = member_select
    clickable_condition = MagicMock()

    with (
        patch("main.summarize_page", return_value=""),
        patch(
            "main.EC.element_to_be_clickable",
            return_value=clickable_condition,
        ) as element_to_be_clickable,
        patch("main.Select") as select,
    ):
        main.select_member_ticket_quantity(driver, wait, ticket_count=2)

    locator = element_to_be_clickable.call_args.args[0]
    assert locator[0] == main.By.XPATH
    assert "translate(@data-product" in locator[1]
    assert "'\"category\":\"member\"'" in locator[1]
    assert locator[1].endswith("]//select")
    wait.until.assert_called_once_with(clickable_condition)
    select.assert_called_once_with(member_select)
    select.return_value.select_by_value.assert_called_once_with("2")


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
