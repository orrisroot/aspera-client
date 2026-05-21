# Aspera Node API Client

A CLI tool for IBM Aspera Node API. Supports file listing and high-speed downloads via ascp.

## Requirements

- Python 3.9+
- [Aspera Connect SDK](https://www.ibm.com/products/aspera-connect) (installed at `~/.aspera/connect/bin/ascp`)

## Installation

```bash
pip install -e .
```

Or:

```bash
pip install requests pyyaml
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

### Download a File

```bash
aspera download /remote/path/to/file.zip /local/destination/
```

Example:
```bash
aspera download /shared/largefile.iso ./downloads/
```

### Options

```
aspera [-c config.yaml] [--host HOST] [--port PORT] [--user USER] [--password PASS] {list|download} ...

aspera download [-i identity_file] <remote_path> <local_dest>
  -i, --identity-file  Path to Aspera SSH identity key
```

## Progress Display

During downloads, real-time progress is displayed by ascp:

```
SRPBS_OPEN.tar.gz  50%  16.0MB  188.0Mb/s  1:20:24 ETA
```

## API Flow

1. Connect to Aspera Node API via **Basic Authentication**
2. List files via **`POST /files/browse`** (JSON body: `{"path": "/dir"}`)
3. Request a transfer token via **`POST /files/download_setup`**
4. Execute high-speed transfer via **`ascp -W <token>`**

## License

MIT
