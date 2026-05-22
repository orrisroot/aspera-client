# Aspera Node API Client

A CLI tool for IBM Aspera Node API. Supports file listing and high-speed downloads via ascp.

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
host: "node.example.com"
port: 9092
user: "node_user"
password: "your_password"
verify_ssl: false  # Set to false for self-signed certificates
path_prefix: ""    # URL path prefix (e.g., "/node_api")
timeout: 30        # Request timeout in seconds
private_key_file: ""  # Path to PEM private key for dynamic key authentication
```

## Usage

### List Files

```bash
aspera list [/remote/path]
```

Examples:
```bash
aspera list /
aspera list /shared/documents
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
  --fields FIELDS         Comma-separated fields to display
```

### Download a File

```bash
aspera download /remote/path/to/file.zip /local/destination/
```

Examples:
```bash
aspera download /shared/largefile.iso ./downloads/
aspera download /shared/file1.txt /shared/file2.txt ./downloads/
```

#### Download Options

```bash
aspera download <remote_path>... <local_dest> [options]

  -r, --recursive         Download directories recursively
  --dry-run               Show transfer specs without executing
  --resume                Resume interrupted transfer
  -f, --format FORMAT     Output format: text, json (default: text)
  -q, --quiet             Suppress ascp progress bar output
  -M, --multi-session N   Number of concurrent transfer sessions (default: 1)
```

### Global Options

```
aspera [-c config.yaml] [--host HOST] [--port PORT] [--user USER] [--password PASS] {list|download} ...
```

## Authentication

This client supports two authentication methods:

### Basic Authentication

Configure `user` and `password` in `config.yaml` or via `--user` / `--password` CLI flags.

### Dynamic Key Authentication

For enhanced security, configure `private_key_file` in `config.yaml` pointing to a PEM-encoded RSA private key. The client will:

1. Generate a public key from the private key
2. Send the public key during download setup
3. Receive an `ssh_private_key` from the API
4. Use it for ascp authentication via `ASPERA_SCP_SSH_PRIVATE_KEY` environment variable

## Progress Display

During downloads, real-time progress is displayed by ascp:

```
SRPBS_OPEN.tar.gz  50%  16.0MB  188.0Mb/s  1:20:24 ETA
```

Use `--quiet` to suppress the progress bar, or `--format json` for structured JSON output (stdout) with progress messages on stderr.

## API Flow

1. Connect to Aspera Node API via **Basic Authentication** or **Dynamic Key Authentication**
2. List files via **`POST /files/browse`** (JSON body: `{"path": "/dir", "count": 1000, "skip": 0}`)
3. Request a transfer token via **`POST /files/download_setup`**
4. Execute high-speed transfer via **`ascp -W <token>`**

## License

MIT
