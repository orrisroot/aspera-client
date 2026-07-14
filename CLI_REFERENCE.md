# CLI Usage

## Global Options

```bash
aspera [-c config.yaml] [--url URL] [--user USER] [--password PASS] {list|find|download|setup} ...
```

- `-c, --config`: Path to configuration file (default: config.yaml)
- `--url`: Aspera Node server URL (overrides config, e.g. `https://host:9092`). Port is optional: defaults to 80 for `http`, 443 for `https`.
- `--user`: Username (overrides config)
- `--password`: Password (overrides config)

## List Files

```bash
aspera list [/remote/path]
```

Examples:
```bash
aspera list /
aspera list /shared/documents
aspera list / --gen4 --file-id abc123
```

Output:
```
Directory: /shared/documents (3 items)

   Size   Modified          Name
dr -      2026-05-24T00:00:00Z reports
fw 12K    2026-05-23T12:00:00Z readme.txt
l- 256    2026-05-23T11:00:00Z latest
```

**Attribute column** (2 chars): `d`=directory, `f`=file, `l`=symlink + `r`=read, `w`=write, `a`=admin, `-`=none

**Color coding**:
- Directories → blue (bold)
- Symlinks → cyan
- Archives (.zip, .gz, etc.) → magenta
- Media files (.jpg, .mp4, .mp3, etc.) → yellow

### List Options

```bash
aspera list [/remote/path] [options]

  -n, --count COUNT       Max entries per page (default: 1000)
  -r, --recursive         Recursively list subdirectories
  --sort FIELD            Sort field: name, size, modified, type, depth (default: name)
  --reverse               Reverse sort order
  --dirs-first            Show directories before files
  --type TYPE             Filter by type: file, directory, symbolic_link
  -f, --format FORMAT     Output format: table, json, csv (default: table)
  --fields FIELDS         Comma-separated fields to display. Use '-' prefix to exclude (e.g., '-id,-path')
  --gen4                  Use gen4 API (Accept-Version: 4.0, iteration_token pagination)
  --file-id FILE_ID       Gen4 file ID to browse (instead of path)
  --matcher PATTERN       File matcher pattern (glob, regex, or None for all). For --find command.
```

## Find Files

Search for files matching a pattern:

```bash
aspera find /search/root 'pattern'
```

Examples:
```bash
aspera find / '*.txt'
aspera find / '^test.*'
aspera find / 'size>1000'
aspera find / '*.log' -r
```

### Find Options

```bash
aspera find [path] pattern [options]

  -r, --recursive         Recursively search subdirectories
  -n, --count COUNT       Max entries per page (default: 1000)
  -f, --format FORMAT     Output format: table, json, csv (default: table)
  --fields FIELDS         Comma-separated list of fields to display
  --gen4                  Use gen4 API
  --file-id FILE_ID       Gen4 file ID to search from
```

**Pattern types:**
- **Glob**: `*.txt`, `*.log` (fnmatch style)
- **Regex**: `^test.*`, `[0-9]+\.csv`
- **Field comparison**: `size>1000`, `type=file`, `depth>=2`

## Download a File

```bash
aspera download /remote/path/to/file.zip /local/destination/
```

Examples:
```bash
aspera download /shared/largefile.iso ./downloads/
aspera download /shared/file1.txt /shared/file2.txt ./downloads/
aspera download /remote/path --gen4 --file-id abc123
```

### Download Options

```bash
aspera download <remote_path>... <local_dest> [options]

  --dry-run               Show transfer specs without executing
  --resume                Resume interrupted transfer
  -f, --format FORMAT     Output format: text, json (default: text)
  -q, --quiet             Suppress ascp progress bar output
  -M, --multi-session N   Number of concurrent transfer sessions (default: 1)
  --gen4                  Use gen4 transfer spec
  --file-id FILE_ID       Gen4 file ID for transfer
  --retries N             Max retry attempts on transient failure (default: 3)
  --timeout SECS          Transfer timeout in seconds (default: 120)
  --ascp-path PATH        Path to ascp binary (overrides auto-detection)
  --verbose               Enable verbose ascp output (-v flag)
```

**Retry behavior:** Transfers are automatically retried on transient failures (network errors, token expiry, FASP handshake issues) with exponential backoff. Non-retryable errors (authentication, permission denied, disk full) fail immediately. The default transfer timeout is 120 seconds (override with `--timeout`).

**Automatic key application:** After running `setup`, the bypass key and fallback certificate are automatically detected and applied to download commands. The bypass key is used for token authentication, and the fallback certificate enables HTTP fallback transfer (via `-I` and `-y 1` flags). The fallback port is taken from the API response (`https_fallback_port`) or defaults to 443.

## Progress Display

During downloads, real-time progress is displayed by ascp:

```
SRPBS_OPEN.tar.gz  50%  16.0MB  188.0Mb/s  1:20:24 ETA
```

Use `--quiet` to suppress the progress bar, or `--format json` for structured JSON output (stdout) with progress messages on stderr.
