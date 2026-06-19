# Changelog

## 0.1.0-beta.1

First GitHub beta.

### Added

- Firefox/Selenium login for SFMOMA member accounts.
- General Admission date and member-ticket quantity selection.
- Interactive confirmation before completing a reservation.
- Experimental `--auto` mode for completing checkout without prompts.
- Private diagnostic screenshots and HTML for troubleshooting.
- `sfm` console command and GitHub installation workflow.

### Known Limitations

- Special exhibition mode can select a requested entry time or list available
  times and prompt for one, then follows the General Admission quantity,
  confirmation, and checkout flow, including `--auto`.
- `--auto` is experimental and has not been verified through a live final
  ticket acquisition.
- Live browser behavior depends on the current SFMOMA website and may break
  when its markup or checkout flow changes.

This project is independent software and is not affiliated with, endorsed by,
or sponsored by the San Francisco Museum of Modern Art.
