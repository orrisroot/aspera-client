# aspera-client API Reference

Welcome to the API reference for the `aspera-client` library. This Python package provides high-speed file transfer, listing, searching, and setup capabilities using the IBM Aspera Node API (both Gen3 and Gen4).

The package is strictly organized under a modular architecture following the Single Responsibility Principle:
- **`models/`**: Data definitions and configurations (`AsperaConfig`, `AsperaEnvironment`, `PageToken`).
- **`core/`**: Connection management, REST API client (`AsperaConnection`), and exceptions.
- **`api/`**: High-level, pure-Python APIs (`browse`, `download`, `setup_environment`).

---

## 1. Package-Level Unified Imports

You can directly import all key classes and functions from the root package level without worrying about the underlying subpackage folder layout:

```python
from aspera_client import (
    AsperaConnection,
    AsperaConfig,
    AsperaEnvironment,
    PageToken,
    browse,
    download,
    setup_environment,
    AsperaNodeError,
    AsperaAuthError,
    AsperaApiError,
)
```

---

## 2. Quick Start

Below is a typical workflow demonstrating how to initialize the environment, configure the connection, list directories, and download files using custom workspace paths.

```python
from aspera_client import AsperaConfig, AsperaEnvironment, AsperaConnection, browse, download, setup_environment

# 1. Create a connection config and a tool installation workspace
config = AsperaConfig(
    host="node.example.com",
    user="your_username",
    password="your_password"
)
# Custom directory to place downloaded tools and certs (defaults to ~/.aspera/connect)
env = AsperaEnvironment(base_dir="./my_aspera_tools")

# 2. Setup the environment by installing Aspera SDK and generating bypass keys (Run once)
setup_environment(env=env, quiet=True)

# 3. Open connection session and execute operations
client = AsperaConnection(config=config, env=env)
with client:
    # List remote files (automatically handles paginations)
    entries, next_token = browse(client, path="/")
    for entry in entries:
        print(f"{entry['name']} ({entry['type']})")

    # Download files using the environment (transfers via ascp automatically)
    result = download(client, remote_paths=["/remote/file.txt"], local_dest="./downloads")
    print("Download Status:", result["status"])
```

---

## 3. Data Models (`models/` Package)

### `AsperaConfig` (`aspera_client.models.config`)
A data class containing parameters for connecting to the Aspera Node API.

#### Fields
| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `host` | `str` | `"localhost"` | Host name or IP address of the Aspera Node server. |
| `port` | `int` | `9092` | The port number of the Node API. When a `url` is provided without an explicit port, defaults to 80 (`http`) or 443 (`https`). |
| `user` | `str \| None` | `None` | Access Key ID / Username for HTTP Basic Auth. |
| `password` | `str \| None` | `None` | Secret Key / Password for HTTP Basic Auth. |
| `verify_ssl` | `bool` | `True` | Whether to verify SSL certificates. Set `False` for self-signed certificates. |
| `timeout` | `int` | `30` | HTTP request timeout in seconds. |
| `dynamic_key` | `str \| None` | `None` | PEM-encoded RSA private key for dynamic key authentication. |
| `accept_v4` | `bool` | `True` | Whether to allow using Gen4 API features (`Accept-Version: 4.0`). |

#### Class Methods
- **`AsperaConfig.from_dict(data: dict) -> AsperaConfig`**
  Builds an `AsperaConfig` instance from a dictionary, auto-resolving Host and Port if a unified `url` field is provided. When the URL omits a port, the default port is determined by the scheme (`http` → 80, `https` → 443).

---

### `AsperaEnvironment` (`aspera_client.models.environment`)
Manages paths and folders for downloaded SDK binaries (`ascp`), bypass keys, fallback certificates, and configurations. By customizing the `base_dir`, you can completely isolate and bundle the library's required tools.

#### Fields
| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `base_dir` | `str` | `~/.aspera/connect` (expanded) | Directory where the SDK binaries and keys are stored. |

#### Properties (Auto-resolved Paths)
- `bin_dir`: Binaries directory (`{base_dir}/bin`).
- `client_dir`: Configurations and certs directory (`{base_dir}/client`).
- `ascp_path`: Executable path for `ascp` (resolves to `ascp` or `ascp.exe` depending on OS).
- `bypass_key_path`: Path to SSH bypass RSA key (`{client_dir}/aspera_bypass_rsa.pem`).
- `fallback_key_path`: HTTPS fallback private key path (`{client_dir}/aspera_fallback_cert_private_key.pem`).
- `fallback_cert_path`: HTTPS fallback certificate path (`{client_dir}/aspera_fallback_cert.pem`).
- `conf_path`: Configuration file path (`{client_dir}/aspera.conf`).

---

### `PageToken` (`aspera_client.models.page_token`)
Abstracts pagination states, covering offsets (`skip`) for Gen3 API and iteration tokens (`iteration_token`) for Gen4 API.

#### Fields
| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `skip` | `int` | `0` | Skip offset for Gen3 pagination. |
| `iteration_token` | `str \| None` | `None` | Iteration token string for Gen4 pagination. |

---

## 4. Connection Core (`core/` Package)

### `AsperaConnection` (`aspera_client.core.connection`)
Handles HTTP communication and session management with the Aspera Node API.

#### Constructor
- **`AsperaConnection(host=None, port=9092, ..., config=None, env=None)`**
  Initializes session details. Accepts connection parameters or an `AsperaConfig` instance, along with an optional `AsperaEnvironment`.

#### Context Manager Support
Supports the `with` statement, closing the HTTP session automatically upon exit.
```python
with AsperaConnection(config=config) as client:
    # Perform operations...
```

---

### Exception Classes (`aspera_client.core.exceptions`)
All custom exceptions inherit from `AsperaNodeError`.

- **`AsperaNodeError(Exception)`**: Base exception class.
- **`AsperaAuthError(AsperaNodeError)`**: Raised if authentication fails (HTTP 401/403).
- **`AsperaApiError(AsperaNodeError)`**: Raised if the API server returns an error response (HTTP 400+).

---

## 5. High-Level APIs (`api/` Package)

### `browse()` (`aspera_client.api.browse`)
Retrieves list entries in a remote directory, supporting filtering, sorting, glob search, and pagination.

```python
def browse(
    client: AsperaConnection,
    path: str = "/",
    count: int = 1000,
    recursive: bool = False,
    sort_by: str = "name",
    reverse: bool = False,
    dirs_first: bool = False,
    type_filter: str | None = None,
    use_gen4: bool = False,
    file_id: str | None = None,
    matcher: Any = None,
    page_token: PageToken | None = None,
) -> tuple[list[dict[str, Any]], PageToken | None]
```

#### Parameters
- `client`: `AsperaConnection` instance.
- `path`: Remote path to list.
- `count`: Maximum entries per page.
- `recursive`: Set `True` to list directories recursively.
- `sort_by`: Field to sort. Choices: `"name"`, `"size"`, `"modified"`, `"type"`, `"depth"`.
- `reverse`: Reverse the sorting order.
- `dirs_first`: Keep directories sorted before files.
- `type_filter`: Restrict items. Choices: `"file"`, `"directory"`, `"symbolic_link"`.
- `use_gen4`: Enable Gen4 API browsing.
- `file_id`: Gen4 folder ID.
- `matcher`: Match filter (glob expression, regex object, or function).
- `page_token`: Page token. If `None`, page iterations are executed internally, returning all entries at once.

#### Returns
A tuple containing a list of parsed entry dictionaries and a `PageToken` (for the next page, if manual pagination is enabled).

---

### `download()` (`aspera_client.api.download`)
Downloads files and folders from a remote Aspera Node to a local destination, executing `ascp` underneath.

```python
def download(
    client: AsperaConnection,
    remote_paths: list[str] | str,
    local_dest: str,
    dry_run: bool = False,
    resume: bool = False,
    multi_session: int = 1,
    use_gen4: bool = False,
    file_id: str | None = None,
    max_retries: int = 3,
    transfer_timeout: int | None = None,
    quiet: bool = True,
    verbose: bool = False,
    output_format: str = "text",
    private_key: str | None = None,
    private_key_file: str | None = None,
    ascp_path_override: str | None = None,
) -> dict[str, Any]
```

---

### `setup_environment()` (`aspera_client.api.setup_environment`)
Downloads and extracts the Aspera Connect SDK, generates bypass SSH keys, and creates fallback certificates for HTTPS fallback.

```python
def setup_environment(
    install_sdk_flag: bool = True,
    bypass_key_flag: bool = True,
    fallback_key_flag: bool = True,
    version: str | None = None,
    quiet: bool = False,
    env: AsperaEnvironment | None = None,
) -> dict[str, Any]
```
