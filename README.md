# Aspera Node API Client

A CLI tool for IBM Aspera Node API. Supports file listing, searching, and high-speed downloads via ascp.

## Requirements

- Python 3.11+
- [Aspera Connect SDK](https://www.ibm.com/products/aspera-connect) (installed at `~/.aspera/connect/bin/ascp`)
- `cryptography` (for dynamic key authentication)

## Installation

```bash
pip install -e .
```

Or:

```bash
pip install requests pyyaml cryptography
```

## Configuration

Copy and edit the sample configuration file:

```bash
cp config.sample.yaml config.yaml
```

Edit `config.yaml` with your Aspera Node server information:

```yaml
# Aspera Node server URL (replaces separate host/port settings)
url: "https://node.example.com:9092"

user: "node_user"
password: "your_password"

# SSL verification (set to false for self-signed certificates)
verify_ssl: true

# URL path prefix (e.g., "/node_api" for servers behind a proxy)

# Request timeout in seconds
timeout: 30

# Gen4 API support (set to false to disable Accept-Version: 4.0 features)
accept_v4: true

# Optional: RSA private key for dynamic key authentication
# private_key_file: "/path/to/aspera_private_key.pem"
```

## Usage

### Global Options

```bash
aspera [-c config.yaml] [--url URL] [--user USER] [--password PASS] {list|find|download} ...
```

- `-c, --config`: Path to configuration file (default: config.yaml)
- `--url`: Aspera Node server URL (overrides config, e.g. `https://host:9092`)
- `--user`: Username (overrides config)
- `--password`: Password (overrides config)

### List Files

```bash
aspera list [/remote/path]
```

Examples:
```bash
aspera list /
aspera list /shared/documents
aspera list / --gen4 --file-id abc123
```

#### List Options

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

### Find Files

Search for files matching a pattern (mirrors Ruby's `find` command):

```bash
aspera find /search/root 'pattern'
```

Examples:
```bash
aspera find / '*.txt'
aspera find / '^test.*'
aspera find / 'size>1000'
aspera find / -r '*.log'
```

#### Find Options

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

### Download a File

```bash
aspera download /remote/path/to/file.zip /local/destination/
```

Examples:
```bash
aspera download /shared/largefile.iso ./downloads/
aspera download /shared/file1.txt /shared/file2.txt ./downloads/
aspera download /remote/path --gen4 --file-id abc123
```

#### Download Options

```bash
aspera download <remote_path>... <local_dest> [options]

  --dry-run               Show transfer specs without executing
  --resume                Resume interrupted transfer
  -f, --format FORMAT     Output format: text, json (default: text)
  -q, --quiet             Suppress ascp progress bar output
  -M, --multi-session N   Number of concurrent transfer sessions (default: 1)
  --gen4                  Use gen4 transfer spec
  --file-id FILE_ID       Gen4 file ID for transfer
```

## Authentication

This client supports two authentication methods:

### Basic Authentication

Configure `user` and `password` in `config.yaml` or via `--user` / `--password` CLI flags.

### Dynamic Key Authentication

For enhanced security, configure `private_key_file` in `config.yaml` pointing to a PEM-encoded RSA private key. The client will:

1. Generate an SSH public key from the private key (matching Ruby's `Net::SSH::Buffer` format)
2. Send the public key during download setup
3. Receive an `ssh_private_key` from the API
4. Use it for ascp authentication via `ASPERA_SCP_SSH_PRIVATE_KEY` environment variable

## API Support

This client supports both gen3 and gen4 Aspera Node APIs:

| Feature | Gen3 | Gen4 |
|---------|------|------|
| File listing | `POST /files/browse` | `GET /files/:id/files` |
| Pagination | `skip` offset | `iteration_token` |
| Transfer | `POST /files/download_setup` | `transfer_spec_gen4` |
| Sort/Filter | Client-side | Server-side (gen4 browse) |

Enable gen4 features with `--gen4` flag or `accept_v4: true` in config.

## Progress Display

During downloads, real-time progress is displayed by ascp:

```
SRPBS_OPEN.tar.gz  50%  16.0MB  188.0Mb/s  1:20:24 ETA
```

Use `--quiet` to suppress the progress bar, or `--format json` for structured JSON output (stdout) with progress messages on stderr.

## License

MIT
