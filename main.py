import argparse
from datetime import date, datetime
import json
import re
import sys
from pathlib import Path

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
DEFAULT_KEYS_PATH = Path("KEYS.txt")
DEFAULT_OUTPUT_DIR = Path("moma-site-info")
MACOS_FIREFOX_BINARY = Path(
    "/Applications/Firefox.app/Contents/MacOS/firefox"
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
        except json.JSONDecodeError:
            raw_keys = {}
            for line in raw_text.splitlines():
                if ":" not in line and "=" not in line:
                    continue
                separator = ":" if ":" in line else "="
                raw_key, raw_value = line.split(separator, 1)
                key = raw_key.strip().strip("\"'").lower()
                value = raw_value.strip().rstrip(",").strip().strip("\"'")
                raw_keys[key] = value

    email = raw_keys.get("email")
    password = raw_keys.get("pw") or raw_keys.get("password")
    if not email or not password:
        raise RuntimeError(
            f"{path} must contain JSON keys 'email' and 'pw' (or 'password')."
        )

    return email, password


def build_driver(headless: bool) -> webdriver.Firefox:
    options = Options()
    if headless:
        options.add_argument("--headless")
    if MACOS_FIREFOX_BINARY.exists():
        options.binary_location = str(MACOS_FIREFOX_BINARY)

    return webdriver.Firefox(options=options)


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
    screenshot_path = output_dir / f"{name}.png"
    html_path = output_dir / f"{name}.html"
    driver.save_screenshot(str(screenshot_path))
    html_path.write_text(driver.page_source)

    print(f"\nSaved {name}.")
    print(f"Current URL: {driver.current_url}")
    print(f"Page title: {driver.title}")
    print(f"Screenshot: {screenshot_path}")
    print(f"HTML: {html_path}")
    print("\nVisible page text:")
    print(summarize_page(driver))
    return screenshot_path


def open_png_in_new_window(
    driver: webdriver.Firefox,
    output_dir: Path,
    png_path: Path,
) -> None:
    driver.switch_to.new_window("window")
    driver.get(png_path.resolve().as_uri())
    driver.save_screenshot(str(output_dir / "shown-png-window.png"))
    print(f"\nOpened PNG in new browser window: {png_path}")
    print(f"Window verification screenshot: {output_dir / 'shown-png-window.png'}")


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

    username_input = wait.until(EC.element_to_be_clickable((By.ID, "UserName")))
    password_input = wait.until(EC.element_to_be_clickable((By.ID, "Password")))

    username_input.clear()
    username_input.send_keys(email)
    password_input.clear()
    password_input.send_keys(password)

    driver.find_element(By.ID, "loginSubmit").click()

    wait.until(lambda active_driver: "tickets.sfmoma.org" in active_driver.current_url)

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
    wait.until(lambda active_driver: f"date={ticket_date}" in active_driver.current_url)
    wait_for_rendered_body(wait)
    save_page_result(driver, output_dir, "performance-result")


def xpath_string_literal(text: str) -> str:
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    parts = text.split('"')
    return 'concat(' + ', \'"\', '.join(f'"{part}"' for part in parts) + ')'


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
    admission_link = wait.until(EC.element_to_be_clickable((By.XPATH, admission_xpath)))
    link_class = admission_link.get_attribute("class") or ""
    if "disabled" in link_class.split():
        raise RuntimeError(f"Admission option is disabled or sold out: {admission_name}")

    print(f"\nClicking admission option: {admission_name}")
    starting_url = driver.current_url
    dismiss_cookie_banner(driver)
    admission_link.click()
    wait.until(lambda active_driver: active_driver.current_url != starting_url)
    wait_for_rendered_body(wait)

    result_name = "admission-special-result" if is_special else "admission-general-result"
    save_page_result(driver, output_dir, result_name)


def select_general_admission_tickets(
    driver: webdriver.Firefox,
    wait: WebDriverWait,
    output_dir: Path,
    ticket_count: int,
) -> None:
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
    print(f"\nSelecting {ticket_count} member ticket(s).")
    Select(member_select).select_by_value(str(ticket_count))

    submit_button = wait.until(EC.element_to_be_clickable((By.ID, "submit-button")))
    starting_url = driver.current_url
    dismiss_cookie_banner(driver)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
    submit_button.click()
    wait.until(lambda active_driver: active_driver.current_url != starting_url)
    wait_for_rendered_body(wait)
    screenshot_path = save_page_result(driver, output_dir, "ticket-submit-result")
    open_png_in_new_window(driver, output_dir, screenshot_path)


def parse_args() -> argparse.Namespace:
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
            "Click a special exhibition admission option. If no name is given, "
            f"defaults to '{DEFAULT_SPECIAL_ADMISSION}'."
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
        "--keys",
        type=Path,
        default=DEFAULT_KEYS_PATH,
        help="Path to JSON credentials with email and pw keys.",
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
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for verification artifacts.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Seconds to wait for login and ticket page transitions.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    driver = None
    try:
        email, password = load_credentials(args.keys)
        ticket_date = parse_ticket_date(args.date)
        admission_name = args.special if args.special is not None else DEFAULT_ADMISSION
        driver = build_driver(args.headless)
        wait = log_in(driver, email, password, args.output_dir, args.timeout)
        open_performance_page(driver, wait, args.output_dir, ticket_date)
        select_admission(
            driver,
            wait,
            args.output_dir,
            admission_name,
            is_special=args.special is not None,
        )
        if args.special is None:
            select_general_admission_tickets(
                driver,
                wait,
                args.output_dir,
                args.num_tickets,
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


if __name__ == "__main__":
    raise SystemExit(main())
