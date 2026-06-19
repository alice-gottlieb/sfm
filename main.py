import argparse
from datetime import date, datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.select import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = "https://account.sfmoma.org/login/ticketing"
PERFORMANCE_URL = "https://tickets.sfmoma.org/tickets/performance?date={ticket_date}"
DEFAULT_ADMISSION = "General Admission"
DEFAULT_SPECIAL_ADMISSION = "Matisse: A Modern Scandal + General Admission"
MACOS_FIREFOX_BINARY = Path(
    "/Applications/Firefox.app/Contents/MacOS/firefox"
)


def default_config_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "sfm" / "KEYS.json"


def default_output_dir(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    system_name = system_name or platform.system()
    environ = environ or os.environ
    home = home or Path.home()
    if system_name == "Darwin":
        base_dir = home / "Library" / "Application Support"
    elif system_name == "Windows":
        base_dir = Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    else:
        base_dir = Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base_dir / "sfm" / "artifacts"


def resolve_credentials_path(
    explicit_path: Path | None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> Path:
    environ = environ or os.environ
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    if explicit_path is not None:
        return explicit_path.expanduser()
    if environ.get("SFM_KEYS_PATH"):
        return Path(environ["SFM_KEYS_PATH"]).expanduser()
    local_path = cwd / "KEYS.txt"
    if local_path.exists():
        return local_path
    config_path = default_config_path(home)
    if config_path.exists():
        return config_path
    raise RuntimeError(
        "Credentials not found. Pass --keys, set SFM_KEYS_PATH, create "
        "./KEYS.txt, or create ~/.config/sfm/KEYS.json."
    )


def load_credentials(path: Path) -> tuple[str, str]:
    try:
        raw_text = path.read_text()
        raw_keys = json.loads(raw_text)
    except FileNotFoundError:
        raise RuntimeError(f"Credentials file not found: {path}") from None
    except json.JSONDecodeError:
        json_with_commas = re.sub(
            r'("[^"]+"\s*:\s*"[^"]*")\s*\n\s*(")',
            r"\1,\n    \2",
            raw_text,
        )
        try:
            raw_keys = json.loads(json_with_commas)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Could not parse credentials file {path}. Use JSON with "
                "'email' and 'pw' (or 'password') keys."
            ) from exc

    if not isinstance(raw_keys, dict):
        raise RuntimeError(f"Credentials file {path} must contain a JSON object.")

    email = raw_keys.get("email")
    password = raw_keys.get("pw") or raw_keys.get("password")
    if not email or not password:
        raise RuntimeError(
            f"{path} must contain JSON keys 'email' and 'pw' (or 'password')."
        )

    return email, password


def build_driver(headless: bool) -> webdriver.Firefox:
    firefox_binary = (
        MACOS_FIREFOX_BINARY
        if MACOS_FIREFOX_BINARY.exists()
        else shutil.which("firefox")
    )
    if not firefox_binary:
        raise RuntimeError(
            "Firefox was not found. Install Firefox and ensure its executable "
            "is on PATH."
        )

    options = Options()
    if headless:
        options.add_argument("--headless")
    options.binary_location = str(firefox_binary)

    try:
        return webdriver.Firefox(options=options)
    except WebDriverException as exc:
        raise RuntimeError(f"Could not start Firefox: {exc.msg or exc}") from exc


def summarize_page(driver: webdriver.Firefox) -> str:
    body_text = driver.execute_script(
        "return document.body ? document.body.innerText : document.documentElement.innerText;"
    )
    body_text = body_text or ""
    compact_body = "\n".join(line.strip() for line in body_text.splitlines() if line.strip())
    if len(compact_body) > 2000:
        compact_body = compact_body[:2000] + "\n..."
    return compact_body


def wait_for_rendered_body(wait: WebDriverWait) -> None:
    try:
        wait.until(
            lambda active_driver: active_driver.execute_script(
                "return document.readyState === 'complete' && !!document.body;"
            )
        )
    except TimeoutException:
        print("Warning: destination page did not render a body before the timeout.")


def dismiss_cookie_banner(driver: webdriver.Firefox) -> None:
    for button_id in ("onetrust-reject-all-handler", "onetrust-close-btn-container"):
        buttons = driver.find_elements(By.ID, button_id)
        if buttons and buttons[0].is_displayed():
            driver.execute_script("arguments[0].click();", buttons[0])
            return


def save_page_result(
    driver: webdriver.Firefox,
    output_dir: Path,
    name: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        output_dir.chmod(0o700)
    except OSError:
        pass
    screenshot_path = output_dir / f"{name}.png"
    html_path = output_dir / f"{name}.html"
    driver.save_screenshot(str(screenshot_path))
    html_path.write_text(driver.page_source)
    for result_path in (screenshot_path, html_path):
        try:
            result_path.chmod(0o600)
        except OSError:
            pass

    print(f"\nSaved {name}.")
    print(f"Current URL: {driver.current_url}")
    print(f"Page title: {driver.title}")
    print(f"Screenshot: {screenshot_path}")
    print(f"HTML: {html_path}")
    print("\nVisible page text:")
    print(summarize_page(driver))
    return screenshot_path


def open_png_with_system_viewer(png_path: Path) -> None:
    resolved_path = png_path.resolve()
    system_name = platform.system()
    try:
        if system_name == "Darwin":
            subprocess.run(["open", str(resolved_path)], check=True)
        elif system_name == "Windows":
            os.startfile(resolved_path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(resolved_path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Could not open the system image viewer for {resolved_path}."
        ) from exc
    print(f"\nOpened PNG with system image viewer: {resolved_path}")


def log_in(
    driver: webdriver.Firefox,
    email: str,
    password: str,
    output_dir: Path,
    timeout_seconds: int,
) -> WebDriverWait:
    wait = WebDriverWait(driver, timeout_seconds)

    print(f"Opening {LOGIN_URL}")
    driver.get(LOGIN_URL)

    try:
        username_input = wait.until(EC.element_to_be_clickable((By.ID, "UserName")))
        password_input = wait.until(EC.element_to_be_clickable((By.ID, "Password")))
    except TimeoutException as exc:
        raise RuntimeError("The SFMOMA login form did not load.") from exc

    username_input.clear()
    username_input.send_keys(email)
    password_input.clear()
    password_input.send_keys(password)

    driver.find_element(By.ID, "loginSubmit").click()

    try:
        wait.until(lambda active_driver: "tickets.sfmoma.org" in active_driver.current_url)
    except TimeoutException as exc:
        raise RuntimeError(
            "Login did not reach the SFMOMA ticket site. Check your credentials."
        ) from exc

    wait_for_rendered_body(wait)
    print("\nLogin submitted.")
    save_page_result(driver, output_dir, "login-result")
    return wait


def parse_ticket_date(raw_date: str | None) -> str:
    if raw_date is None:
        return date.today().isoformat()
    try:
        return datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise RuntimeError("Date must use YYYY-MM-DD format, for example 2026-06-17.")


def open_performance_page(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    ticket_date: str,
) -> None:
    performance_url = PERFORMANCE_URL.format(ticket_date=ticket_date)
    print(f"\nOpening performance page: {performance_url}")
    driver.get(performance_url)
    try:
        wait.until(lambda active_driver: f"date={ticket_date}" in active_driver.current_url)
    except TimeoutException as exc:
        raise RuntimeError(f"Could not open ticket date {ticket_date}.") from exc
    wait_for_rendered_body(wait)
    available_links = driver.find_elements(
        By.CSS_SELECTOR, "a.event-type-link:not(.disabled)"
    )
    if not available_links:
        raise RuntimeError(
            f"No available admission options were found for {ticket_date}. "
            "The museum may be closed or tickets may be unavailable."
        )
    save_page_result(driver, output_dir, "performance-result")


def xpath_string_literal(text: str) -> str:
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    parts = text.split('"')
    return 'concat(' + ', \'"\', '.join(f'"{part}"' for part in parts) + ')'


def normalize_ticket_time(raw_time: str) -> str:
    normalized = re.sub(r"\s+", " ", raw_time.strip().lower())
    normalized = normalized.replace(".", "")
    try:
        parsed_time = datetime.strptime(normalized, "%I:%M %p")
    except ValueError:
        raise RuntimeError(
            "Time must use 12-hour format, for example '12:00 pm'."
        ) from None
    meridiem = "a.m." if parsed_time.strftime("%p") == "AM" else "p.m."
    return f"{parsed_time.strftime('%I').lstrip('0')}:{parsed_time:%M} {meridiem}"


def select_admission(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    admission_name: str,
    is_special: bool,
) -> None:
    admission_xpath = (
        "//a[contains(concat(' ', normalize-space(@class), ' '), ' event-type-link ') "
        f"and normalize-space(.) = {xpath_string_literal(admission_name)}]"
    )
    try:
        admission_link = wait.until(
            EC.element_to_be_clickable((By.XPATH, admission_xpath))
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Admission option was not found or was unavailable: {admission_name}"
        ) from exc
    link_class = admission_link.get_attribute("class") or ""
    if "disabled" in link_class.split():
        raise RuntimeError(f"Admission option is disabled or sold out: {admission_name}")

    print(f"\nClicking admission option: {admission_name}")
    starting_url = driver.current_url
    dismiss_cookie_banner(driver)
    admission_link.click()
    wait.until(lambda active_driver: active_driver.current_url != starting_url)
    wait_for_rendered_body(wait)

    if is_special:
        try:
            wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "a.time-slot-link")
                )
            )
        except TimeoutException as exc:
            raise RuntimeError(
                f"No entry times were found for special exhibition: {admission_name}"
            ) from exc

    result_name = "admission-special-result" if is_special else "admission-general-result"
    save_page_result(driver, output_dir, result_name)


def select_special_exhibition_time(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    raw_time: str,
) -> None:
    ticket_time = normalize_ticket_time(raw_time)
    time_xpath = (
        "//div[contains(concat(' ', normalize-space(@class), ' '), "
        "' time-slot--row ')]"
        "//a[contains(concat(' ', normalize-space(@class), ' '), "
        f"' time-slot-link ') and normalize-space(.) = {xpath_string_literal(ticket_time)}]"
    )
    try:
        time_link = wait.until(EC.element_to_be_clickable((By.XPATH, time_xpath)))
    except TimeoutException as exc:
        raise RuntimeError(
            f"Special exhibition entry time was not found or unavailable: {raw_time}"
        ) from exc

    print(f"\nClicking special exhibition entry time: {ticket_time}")
    starting_url = driver.current_url
    dismiss_cookie_banner(driver)
    time_link.click()
    try:
        wait.until(lambda active_driver: active_driver.current_url != starting_url)
    except TimeoutException as exc:
        raise RuntimeError(
            f"The page did not advance after selecting entry time: {raw_time}"
        ) from exc
    wait_for_rendered_body(wait)
    save_page_result(driver, output_dir, "special-time-result")


def prompt_for_special_exhibition_time(driver: webdriver.Firefox) -> str:
    time_links = driver.find_elements(By.CSS_SELECTOR, "a.time-slot-link")
    available_times = []
    for time_link in time_links:
        try:
            ticket_time = normalize_ticket_time(time_link.text)
        except RuntimeError:
            continue
        if ticket_time not in available_times:
            available_times.append(ticket_time)

    if not available_times:
        raise RuntimeError("No special exhibition entry times are available.")

    print("\nAvailable special exhibition entry times:")
    for ticket_time in available_times:
        print(f"  - {ticket_time.replace('.', '')}")

    while True:
        try:
            raw_time = input("\nEnter an entry time: ").strip()
        except EOFError:
            raise RuntimeError(
                "No entry time was provided. Use --time for non-interactive runs."
            ) from None

        try:
            ticket_time = normalize_ticket_time(raw_time)
        except RuntimeError as exc:
            print(f"Invalid time: {exc}")
            continue
        if ticket_time in available_times:
            return raw_time
        print(
            f"Time is not available: {raw_time}. "
            "Choose one of the times listed above."
        )


def select_member_ticket_quantity(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    ticket_count: int,
) -> None:
    page_text = summarize_page(driver).lower()
    if (
        "already booked your daily allotment" in page_text
        or "member\tfree\tnot available" in page_text
    ):
        raise RuntimeError(
            "Member tickets are not available for this date. Your account may "
            "have already reached its daily member-ticket allotment."
        )

    try:
        member_select = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//tr[contains(translate(@data-product, "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
                    "'\"category\":\"member\"')]//select",
                )
            )
        )
    except TimeoutException as exc:
        raise RuntimeError(
            "The Member ticket quantity selector was not found."
        ) from exc
    print(f"\nSelecting {ticket_count} member ticket(s).")
    Select(member_select).select_by_value(str(ticket_count))


def select_general_admission_tickets(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    ticket_count: int,
    auto: bool,
) -> None:
    select_member_ticket_quantity(driver, wait, ticket_count)

    submit_button = wait.until(EC.element_to_be_clickable((By.ID, "submit-button")))
    starting_url = driver.current_url
    dismiss_cookie_banner(driver)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
    submit_button.click()
    wait.until(lambda active_driver: active_driver.current_url != starting_url)
    wait_for_rendered_body(wait)
    screenshot_path = save_page_result(driver, output_dir, "ticket-submit-result")
    finish_general_admission_order(
        driver,
        wait,
        output_dir,
        screenshot_path,
        auto,
    )


def finish_general_admission_order(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    screenshot_path: Path,
    auto: bool,
) -> None:
    if auto:
        print(
            "\nExperimental auto mode enabled; submitting this unverified "
            "checkout flow without a prompt."
        )
        submit_purchase_with_diagnostics(
            driver, wait, output_dir, show_intermediate=False
        )
    else:
        open_png_with_system_viewer(screenshot_path)
        if confirm_purchase_prompt():
            submit_purchase_with_diagnostics(
                driver, wait, output_dir, show_intermediate=True
            )
        else:
            print("\nPurchase not submitted.")


def confirm_purchase_prompt() -> bool:
    try:
        answer = input("\nSubmit this order? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer == "y"


def submit_purchase_with_diagnostics(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    show_intermediate: bool,
) -> None:
    try:
        submit_purchase(driver, wait, output_dir, show_intermediate)
    except (RuntimeError, TimeoutException, WebDriverException) as exc:
        try:
            save_page_result(driver, output_dir, "checkout-failure")
        except (OSError, WebDriverException):
            pass
        raise RuntimeError(
            "Checkout failed. No automatic retry was attempted. Review the "
            f"diagnostic artifacts in {output_dir}."
        ) from exc


def submit_purchase(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    show_intermediate: bool,
) -> None:
    try:
        accept_terms = wait.until(
            EC.presence_of_element_located((By.ID, "AcceptTerms"))
        )
    except TimeoutException as exc:
        raise RuntimeError("The terms checkbox was not found.") from exc
    dismiss_cookie_banner(driver)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", accept_terms)
    if not accept_terms.is_selected():
        driver.execute_script("arguments[0].click();", accept_terms)

    click_purchase_proceed(driver, wait)
    payment_review_screenshot = save_page_result(
        driver, output_dir, "payment-review-result"
    )
    if show_intermediate:
        open_png_with_system_viewer(payment_review_screenshot)

    click_purchase_proceed(driver, wait)
    try:
        wait.until(
            lambda active_driver: "purchaseSubmit" not in active_driver.page_source
            or "confirmation" in active_driver.current_url.lower()
            or "confirmation" in active_driver.page_source.lower()
        )
    except TimeoutException as exc:
        raise RuntimeError("The final confirmation page did not load.") from exc
    if "purchaseSubmit" in driver.page_source:
        raise RuntimeError("The final confirmation page could not be verified.")
    confirmation_screenshot = save_page_result(
        driver, output_dir, "confirmation-result"
    )
    open_png_with_system_viewer(confirmation_screenshot)


def click_purchase_proceed(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
) -> None:
    try:
        purchase_button = wait.until(
            EC.element_to_be_clickable((By.ID, "purchaseSubmit"))
        )
    except TimeoutException as exc:
        raise RuntimeError("The checkout Proceed button was not found.") from exc
    starting_url = driver.current_url
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", purchase_button)
    purchase_button.click()
    try:
        wait.until(lambda active_driver: active_driver.current_url != starting_url)
    except TimeoutException as exc:
        raise RuntimeError("Checkout did not advance after clicking Proceed.") from exc
    wait_for_rendered_body(wait)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log in to the SFMOMA ticketing account page with Selenium."
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="Ticket date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "-s",
        "--special",
        nargs="?",
        const=DEFAULT_SPECIAL_ADMISSION,
        default=None,
        metavar="EXHIBITION",
        help=(
            "Open entry times for a special exhibition. With no EXHIBITION, "
            f"defaults to {DEFAULT_SPECIAL_ADMISSION!r}."
        ),
    )
    parser.add_argument(
        "-n",
        "--num-tickets",
        type=int,
        choices=(1, 2),
        default=1,
        help="Number of member General Admission tickets to reserve. Must be 1 or 2.",
    )
    parser.add_argument(
        "-t",
        "--time",
        default=None,
        metavar="TIME",
        help=(
            "Special exhibition entry time in 12-hour format, such as "
            "'12:00 pm'. Requires --special."
        ),
    )
    parser.add_argument(
        "-a",
        "--auto",
        action="store_true",
        help=(
            "EXPERIMENTAL AND UNVERIFIED: skip confirmation prompts, submit the "
            "order automatically, and only open the final confirmation screenshot."
        ),
    )
    parser.add_argument(
        "--keys",
        type=Path,
        default=None,
        help=(
            "Path to JSON credentials. Falls back to SFM_KEYS_PATH, ./KEYS.txt, "
            "then ~/.config/sfm/KEYS.json."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Firefox without opening a visible browser window.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep Firefox open after submitting the login form.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for sensitive screenshots and HTML diagnostics.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Seconds to wait for login and ticket page transitions.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    driver = None
    try:
        if args.time is not None and args.special is None:
            raise RuntimeError("--time requires --special.")

        keys_path = resolve_credentials_path(args.keys)
        output_dir = (
            args.output_dir.expanduser()
            if args.output_dir is not None
            else default_output_dir()
        )
        print(
            f"Warning: screenshots and HTML may contain personal information. "
            f"Artifacts will be stored in {output_dir}.",
            file=sys.stderr,
        )

        email, password = load_credentials(keys_path)
        ticket_date = parse_ticket_date(args.date)
        driver = build_driver(args.headless)
        wait = log_in(driver, email, password, output_dir, args.timeout)
        open_performance_page(driver, wait, output_dir, ticket_date)
        admission_name = args.special or DEFAULT_ADMISSION
        is_special = args.special is not None
        select_admission(
            driver,
            wait,
            output_dir,
            admission_name,
            is_special=is_special,
        )
        if is_special:
            selected_time = args.time or prompt_for_special_exhibition_time(driver)
            select_special_exhibition_time(
                driver,
                wait,
                output_dir,
                selected_time,
            )
        select_general_admission_tickets(
            driver,
            wait,
            output_dir,
            args.num_tickets,
            args.auto,
        )
        if args.keep_open and not args.headless:
            input("\nPress Enter to close Firefox...")
        return 0
    except (RuntimeError, WebDriverException, TimeoutException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if driver and not args.keep_open:
            driver.quit()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
