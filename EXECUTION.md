# Bounded execution agent

`ultramarine_agent` runs a model -> Python tool -> result -> model loop. This can read supplied files, calculate, build a workbook/document and reopen it to check its structure. It is optional; the four existing tools continue to work without an executor.

## Two separate deployments

1. **Horizon:** existing `server.py:mcp`, organization authentication enabled. Holds `PAPERINSTRUMENTS_API_KEY` and calls Paper Instruments.
2. **Dedicated Linux execution host:** runs `python -m executor.service` from the repository root. This uses a dedicated rootless Docker daemon to start one disposable container per Python call. The service receives code/files and an executor token only. Never put the provider key on this host. It must not share the machine with other credentials or workloads.

Horizon hosting documentation does not document a security boundary for arbitrary generated code. Therefore the MCP process never evaluates code locally and refuses agent tasks if the separate executor is missing. MCP versus Python versus Node is a transport choice; the loop and tools provide the ability to do work.

## Executor setup

On a dedicated Linux VM, install Docker in rootless mode with working cgroup resource limits. Build and retain the image:

```sh
docker build -t ultramarine-python:v1 executor
export EXECUTOR_IMAGE="$(docker image inspect ultramarine-python:v1 --format '{{.Id}}')"
# Set EXECUTOR_TOKEN through your host secret manager (32+ random characters).
python -m executor.service
```

The listener is localhost:8090. Place a maintained HTTPS reverse proxy in front of it, with a 4 MiB request limit, 45-second upstream timeout, connection/rate limits and access-log redaction. Never expose the Docker socket. Restrict incoming access where possible. A production operator must verify rootless memory, PID and CPU limits actually apply, patch the host, and monitor capacity. Docker isolates processes but shares the kernel; use a dedicated VM, or replace this adapter with a stronger managed microVM sandbox for hostile multi-tenant use.

Set in Horizon's environment:

```text
ULTRAMARINE_EXECUTOR_URL=https://your-executor.example
ULTRAMARINE_EXECUTOR_TOKEN=<same random value as EXECUTOR_TOKEN>
```

Keep tokens out of Git and chat. The executor token and provider API key are different secrets. `ultramarine_status` reports configuration, not successful backend authentication. Redeploy the review branch only after tests pass; retain main as rollback.

## Limits and boundaries

- Inputs and returned artifacts: 20 flat filenames, 2 MiB decoded total. Caller supplies base64 bytes, not paths or remote URLs. File content goes to the executor; extracted data/tool output may also go to the model.
- Each call starts fresh: files carry forward, Python variables do not. Outputs are returned inline, no durable remote storage. Caller decodes and saves files. Partial artifacts on failure are explicitly unfinished.
- Offline container: no network, no host mounts, nonroot UID, read-only image, dropped capabilities, 64 PIDs, 512 MiB RAM, one CPU, limited tmpfs and file size, 25-second code timeout. Outer 35-second watchdog forcibly removes the container.
- Six model turns default, 12 maximum; up to four sequential Python calls per turn. A 240-second task deadline is checked before requests/tools, with bounded individual timeouts. A stalled remote executor may finish its current container after the caller times out, but cannot continue the model loop. No hidden automatic retries.
- Total-token and estimated-dollar budgets are checked before each request using a conservative UTF-8 input estimate. Rates: USD0.15/M input and USD0.50/M output, ignoring cache discounts. This is an application estimate, not a provider hard billing cap. Keep provider account limits separately. Oversized context stops rather than silently discarding history.
- No host MCP delegation, email, web browsing, package installation or arbitrary host shell. The image pins paper-docx 0.2.1, paper-pptx 0.2.1 and paper-xlsx 0.2.2 (versions the user verified in their separate environment), plus pandas, pypdf and reportlab. Imports remain docx, pptx and openpyxl. Do not install the upstream Office distributions into this same image. Successful image build/import smoke tests are required before deployment; the local Windows checks do not establish package installation in Linux.
- The caller must retain original input bytes before calling. All edits happen on serialized copies, but generated code can overwrite those copies inside its workspace. Returned files are candidates, never authoritative replacements for originals. No local files are modified by this MCP tool.
- `low`, `high`, `max` reasoning supported. Output budget includes reasoning. Source/model/tool content remains untrusted. Code can create wrong or malicious files despite isolation, so never open output with macros enabled or run returned executable files automatically.

## Test and release

Run `python -m unittest -v` after installing requirements. Unit tests mock provider/executor, verify transcript handling, budget rejection, truncation refusal, no retries, file traversal rejection and Docker flags. CI additionally builds the real container and runs a synthetic smoke test (no key). Before production: verify a network-denial test, environment isolation, timeout cleanup and a tiny XLSX generation/reopen through the deployed MCP. Host still performs independent formula checks, spreadsheet recalculation and visual QA. No live execution or deployment is implied by passing mocked tests.

Example tool input: `{"task":"Create result.csv with x and x_squared for 1 through 5; read it back and verify.","data_classification":"synthetic","max_turns":4}`.

## Official references reviewed

- https://docs.paperinstruments.com/docs/ultramarine/chat-completions (function call loop, reasoning history, truncated calls, usage)
- https://docs.paperinstruments.com/docs/ultramarine/prompting-and-packages
- https://gofastmcp.com/deployment/prefect-horizon (hosting, secrets, authentication, PR previews)
- https://docs.docker.com/engine/containers/run/ (isolation, network and resource controls)
- https://docs.docker.com/engine/security/rootless/ (daemon isolation and resource-limit prerequisites)

The controller preserves provider `reasoning_content` only in the in-memory conversation as required by its documented tool loop. It never returns or logs that field.
