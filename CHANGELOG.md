# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-11-13

### Changed
- A Ctrl+C during a transfer stops `ascp` and raises `KeyboardInterrupt` instead of returning exit code 130 as a failed transfer. A second Ctrl+C while stopping kills `ascp`. The CLI prints `Interrupted.` and exits 130.
- `quiet` silences the transfer's own messages (fallback state, command line, retries, success). A failure is still reported with its reason.

### Fixed
- Reported the result of a transfer once instead of twice.
- Kept the file list of a multi-file transfer until its last attempt, so a retry no longer runs `ascp` without it.
- Warned about a missing SSH private key only when nothing else can authenticate the transfer.
- `aspera setup` installs the SDK on a Mac and on ARM Linux: platform names follow IBM's listing (`osx-arm64`, `linux-arm64`, with `osx-universal` as a fallback), and the macOS zip is unpacked with its permissions and symlinks. Versions are compared numerically.
- `aspera setup` extracts only the runtime folders, now including `lib/libstdc++.so.6`, and keeps every path and link inside the install folder. A failed install leaves the existing SDK in place.

## [0.1.0]

- Initial release.
