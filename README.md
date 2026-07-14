# aspera-client

Client for IBM Aspera combining **Node API** (Gen3/Gen4) for file operations and **ascp** for high-speed transfer.

**Features**

- **Directory listing** — browse remote paths via Node API with sorting, filtering, recursive traversal
- **File search** — find files via Node API by glob, regex, or field comparison
- **High-speed download** — transfer files via `ascp` (FASP protocol) with automatic retry and HTTP fallback
- **Environment setup** — install Aspera Connect SDK and generate authentication keys

**Interface**

- [CLI Reference](./CLI_REFERENCE.md) — `aspera` command for terminal operations
- [Python API Reference](./API_REFERENCE.md) — importable library for script integration

## Requirements

- Python 3.11+
- `cryptography` (for key generation and dynamic key authentication)
- Aspera Connect SDK (installed via `aspera setup`)

## Installation

```bash
pip install -e .
```

Or install dependencies directly:

```bash
pip install requests pyyaml cryptography rich
```

## Setup

Run the setup command to install `ascp` (from Aspera Connect SDK) and generate authentication keys:

```bash
aspera setup
```

Options:
- `--no-sdk`: Skip SDK download (use existing `ascp`)
- `--no-bypass-key`: Skip bypass key generation
- `--no-fallback-key`: Skip fallback key generation
- `--version VERSION`: Install a specific SDK version

The setup command creates:
- `~/.aspera/connect/bin/ascp` — Aspera high-speed transfer client (from Connect SDK)
- `~/.aspera/connect/client/aspera_bypass_rsa.pem` — Bypass key for token authentication (used with `-i` flag)
- `~/.aspera/connect/client/aspera_fallback_cert.pem` — Fallback certificate for HTTP fallback (used with `-I` flag)
- `~/.aspera/connect/client/aspera.conf` — Aspera configuration file (copied from SDK)
- `~/.aspera/connect/client/meta-data.xml` — SDK metadata

Generated files are stored in `~/.aspera/connect/client/` to keep them separate from SDK files.

Keys are automatically applied to download commands.

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

# Request timeout in seconds
timeout: 30

# Gen4 API support (set to false to disable Accept-Version: 4.0 features)
accept_v4: true

# Optional: RSA private key for dynamic key authentication
# private_key_file: "/path/to/aspera_private_key.pem"
```

## Documentation

- [CLI Reference](./CLI_REFERENCE.md) — command-line usage and options
- [Python API Reference](./API_REFERENCE.md) — library usage, quick start, and class/function docs

## Authentication

This client supports two authentication methods:

### Basic Authentication

Configure `user` and `password` in `config.yaml` or via `--user` / `--password` CLI flags.

### Dynamic Key Authentication

For enhanced security, configure `private_key_file` in `config.yaml` pointing to a PEM-encoded RSA private key. The client will:

1. Generate an SSH public key from the private key
2. Send the public key during download setup
3. Receive an `ssh_private_key` from the API
4. Use it for ascp authentication via `ASPERA_SCP_SSH_PRIVATE_KEY` environment variable

### Bypass Key Authentication

After running `aspera setup`, the bypass key (`~/.aspera/connect/client/aspera_bypass_rsa.pem`) is automatically used for token authentication. This key enables transfers when the API does not return an `ssh_private_key`, preventing authentication failures and password prompts.

### HTTP Fallback

When the primary FASP transfer fails, the client automatically falls back to HTTP transfer. The fallback is enabled via ascp's `-y 1` flag, using the fallback certificate (`-I`) and port (`-t`, default 443). The server's `https_fallback` and `https_fallback_port` fields from the API response are respected when available.

**Fallback behavior:**
- If the FASP port is closed but the host responds, fallback triggers in ~2 seconds
- If the host is unreachable, the transfer times out after `--timeout` seconds (default: 120s) and retries (default: 3 times)
- Use `--verbose` for detailed ascp output, or check the log messages showing fallback status

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
