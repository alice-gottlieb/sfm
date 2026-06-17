# sfm

Easy CLI for getting SFMOMA member tickets.

## Requirements

- Python 3.11+
- Firefox installed
- `uv` installed
- SFMOMA account credentials in `KEYS.txt`

## Setup

Create `KEYS.txt` in the project root:

```json
{
  "email": "you@example.com",
  "pw": "your-password"
}
```

Install dependencies and the `sfm` command:

```bash
uv sync
uv tool install --editable .
```

After installation, verify the command is available:

```bash
sfm --help
```

## Usage

Get one General Admission member ticket for a date:

```bash
sfm 2026-06-18
```

Run with Firefox hidden:

```bash
sfm 2026-06-18 --headless
```

Choose one or two member tickets:

```bash
sfm 2026-06-18 -n 2
```

By default, the CLI pauses on the purchase page, opens a screenshot in the system image viewer, and asks before submitting the order.

Skip prompts and only show the final confirmation screenshot after tickets are acquired:

```bash
sfm 2026-06-18 -n 1 --auto
```

If no date is provided, `sfm` defaults to today.

## Special Exhibitions

The `--special` / `-s` path is still under development and is not yet functional end to end. Use the default General Admission path for now.

## Generated Files

Screenshots and saved HTML are written to `moma-site-info/` for debugging. Credentials, screenshots, virtual environments, and generated metadata are ignored by git.
