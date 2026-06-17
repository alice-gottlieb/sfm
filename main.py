import argparse
import json
import re
import sys
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = "https://account.sfmoma.org/login/ticketing"
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


def log_in(
    driver: webdriver.Firefox,
    email: str,
    password: str,
    output_dir: Path,
    timeout_seconds: int,
) -> None:
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

    try:
        wait.until(lambda active_driver: active_driver.current_url != LOGIN_URL)
    except TimeoutException:
        pass

    try:
        wait.until(
            lambda active_driver: active_driver.execute_script(
                "return document.readyState === 'complete' && !!document.body;"
            )
        )
    except TimeoutException:
        print("Warning: destination page did not render a body before the timeout.")

    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = output_dir / "login-result.png"
    html_path = output_dir / "login-result.html"
    driver.save_screenshot(str(screenshot_path))
    html_path.write_text(driver.page_source)

    print("\nLogin submitted.")
    print(f"Current URL: {driver.current_url}")
    print(f"Page title: {driver.title}")
    print(f"Screenshot: {screenshot_path}")
    print(f"HTML: {html_path}")
    print("\nVisible page text:")
    print(summarize_page(driver))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log in to the SFMOMA ticketing account page with Selenium."
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
        driver = build_driver(args.headless)
        log_in(driver, email, password, args.output_dir, args.timeout)
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
