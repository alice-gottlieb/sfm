# sfm

`sfm` is a beta CLI that automates SFMOMA member General Admission ticket
reservations and opens available special-exhibition entry times with Firefox
and Selenium.

This project is independent software and is not affiliated with, endorsed by,
or sponsored by the San Francisco Museum of Modern Art.

## Requirements

- Python 3.11 or 3.12
- Firefox
- [`uv`](https://docs.astral.sh/uv/)
- An SFMOMA member account

## Install

Install the GitHub beta:

```bash
uv tool install "git+https://github.com/alice-gottlieb/sfm.git@v0.1.0-beta.1"
```

For development from a local clone:

```bash
uv sync --locked
uv tool install --editable .
```

Verify the command:

```bash
sfm --help
```

## Credentials

Credentials must be JSON:

```json
{
  "email": "you@example.com",
  "pw": "your-password"
}
```

`sfm` checks these locations in order:

1. `--keys /path/to/credentials.json`
2. The `SFM_KEYS_PATH` environment variable
3. `KEYS.txt` in the current directory
4. `~/.config/sfm/KEYS.json`

Credential files should only be readable by your user account and must never
be committed to git.

## Usage

Reserve one General Admission member ticket:

```bash
sfm 2026-06-18
```

Run Firefox headlessly:

```bash
sfm 2026-06-18 --headless
```

Select one or two member tickets:

```bash
sfm 2026-06-18 -n 2
```

Without a date, `sfm` uses today. Normal mode opens a purchase-page screenshot
and asks for confirmation before completing checkout.

### Experimental Auto Mode

```bash
sfm 2026-06-18 -n 1 --auto
```

`--auto` / `-a` skips all confirmation prompts and attempts to acquire the
tickets immediately. It only opens the final confirmation screenshot.

**Auto mode is experimental and has not been verified through a live final
ticket acquisition. Use it at your own risk.**

### Special Exhibitions

Open the available entry times for the default special exhibition:

```bash
sfm 2026-06-18 --special
```

Select a different special exhibition by its exact button text:

```bash
sfm 2026-06-18 -s "Exhibition Name + General Admission"
```

Select an available entry time using 12-hour format:

```bash
sfm 2026-06-18 --special --time "12:00 pm"
```

`--time` / `-t` requires `--special` / `-s`. Without `--time`, the CLI lists
all available entry times and prompts you to enter one. After choosing the
time, the CLI follows the same flow as General Admission: it selects the member
quantity specified by `--num-tickets` / `-n`, clicks Continue, displays the
order screenshot, and asks for confirmation before completing checkout.
`--auto` skips the confirmation prompts and intermediate images in both modes.

## Sensitive Artifacts

Screenshots and saved HTML can contain your name, email, address, and ticket
details. By default they are stored in a private user data directory:

- macOS: `~/Library/Application Support/sfm/artifacts`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/sfm/artifacts`
- Windows: `%LOCALAPPDATA%\sfm\artifacts`

Override this with `--output-dir`. Checkout failures save a
`checkout-failure` diagnostic and never retry the purchase automatically.

## Development

```bash
uv sync --locked
uv run pytest
uv build
```

Live Selenium tests require account credentials and are intentionally not run
in CI.
