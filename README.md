# Ultramarine FastMCP server

Optional model delegation through Paper Instruments, deployable on **Prefect Horizon**.
Python 3.12 recommended. No Node installation or OpenAI SDK required.

## Deploy

1. In https://horizon.prefect.io connect this repository and select `main`.
2. Set the entrypoint to **`server.py:mcp`**. Dependencies come from `requirements.txt`.
3. Add environment variable **`PAPERINSTRUMENTS_API_KEY`**. Paste the actual API key into the **value** field. The capitalized name is the variable name, not the secret.
4. Enable Horizon **Authentication** and limit access to intended users. The provider key pays for all callers. Never expose an unauthenticated public endpoint.
5. Deploy and copy Horizon's `/mcp` URL into your assistant's custom MCP connector configuration. Complete the Horizon login.
6. In Inspector call `ultramarine_status`, then `ultramarine_health`, then `ultramarine_models`. Finally call `ultramarine_run` with the synthetic smoke test below. Only the last generates tokens and incurs inference charges.

Horizon manages remote OAuth. The provider key belongs only in the server environment, never in tool arguments or GitHub. Local Windows environment variables are not automatically copied to Horizon.

## Tools

| Tool | Purpose |
| --- | --- |
| `ultramarine_status` | Local settings, supported controls and limits; no network |
| `ultramarine_health` | Authenticated GET checks key and model listing; no generation |
| `ultramarine_models` | Available provider model IDs; only `ultramarine-1-flash` is enabled for execution |
| `ultramarine_run` | One bounded summarization, extraction, classification, editing, drafting or analysis task |

`reasoning_effort` is **low / high / max**, not separate models. `medium` is unsupported and rejected. This wrapper defaults to `high`; the provider defaults to and recommends `max`. Use `low` for simple work, `high` for routine work, and `max` for difficult synthesis, then evaluate quality. These are initial routing heuristics, not measured benchmarks.

Other run parameters: `task`, `source_text`, `operation`, `max_completion_tokens` (default 8192, local ceiling 16384), `output_format` (`text` or `json`), `data_classification`, and `external_processing_authorized`. JSON mode checks parseability and object shape; it does not validate a custom schema or source quotations. All answers require host review.

Synthetic smoke test:

```json
{
  "task": "Summarize the supplied statement in one sentence without adding facts.",
  "source_text": "The synthetic project has three phases and starts in January 2030.",
  "operation": "summarize",
  "reasoning_effort": "low",
  "max_completion_tokens": 4096,
  "data_classification": "synthetic"
}
```

## Failure behavior and controls

- `status: candidate` means the host must check the answer, especially numerical claims and citations. Model content cannot override the response envelope.
- `status: fallback` means the calling assistant should continue using its own model or deterministic tools. This server cannot switch the host model itself.
- Missing/invalid keys, disabled service, timeouts, malformed output, truncation, unexpected tool calls and provider failures produce sanitized fallback results. No automatic retries or recursive tool loops. `retryable` is a hint, not a command to retry; quotas can require billing intervention.
- Set `ULTRAMARINE_DISABLED=1` in Horizon to disable all upstream calls. Remove it or set `0` to restore service.
- Two concurrent upstream requests per process, 120-second socket timeout, 48,000-byte serialized-message cap, and 16,384 output-token ceiling bound individual calls. Reasoning tokens count toward the output ceiling and cost. The byte cap is not a tokenizer or a claim about the model's context window. The socket timeout is not a total wall-clock deadline.
- This is not an account-wide rate limiter or spend cap. Multiple Horizon workers have independent concurrency limits. Configure provider billing controls and restrict Horizon access.
- Private/internal/confidential data requires explicit external-processing authorization. The caller is responsible for correct classification and removing secrets; this is not a DLP scanner.
- No prompt or response logging in this code, no persistent conversation store. Horizon/provider logging and retention are governed by their own settings. No host files, shell, arbitrary URLs, or model-generated tools are executed.
- MCP and local API scripts share the same upstream service. Neither fixes a provider outage or invalid key; the host workflow is the actual fallback.

## Local development

```sh
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -r requirements.txt
python -m unittest -v
fastmcp inspect server.py:mcp
python server.py
```

The last command uses local stdio. `app` is also exported for ASGI hosts, which must supply authentication before exposing it publicly. Horizon imports `mcp` directly. `.env.example` is documentation only; files are not loaded automatically.

PowerShell session-only masked key input:

```powershell
$keyInput = Read-Host 'Paper Instruments API key' -AsSecureString
$env:PAPERINSTRUMENTS_API_KEY = [System.Net.NetworkCredential]::new('', $keyInput).Password
Remove-Variable keyInput
[bool]$env:PAPERINSTRUMENTS_API_KEY
```

Optional persistence on your own Windows account:

```powershell
[Environment]::SetEnvironmentVariable('PAPERINSTRUMENTS_API_KEY', $env:PAPERINSTRUMENTS_API_KEY, 'User')
```

User environment variables are not encrypted vault storage. Restart the client process to inherit changes. Never paste the key into chat. For Horizon use its environment settings instead.

## Validation and rollback

Unit tests mock the upstream response and require no secrets. The MCP integration test uses a real in-process FastMCP client. GitHub Actions installs dependencies and runs both. Check Actions before deployment; a successful unit test alone is not proof of live authentication or model generation. Run the Inspector sequence after deployment.

To roll back, redeploy a prior known-good commit in Horizon or revert the offending GitHub commit. Keep the existing host workflow available. Secrets are not included in backups; restore them through the hosting secret configuration.

## Documentation reviewed

- https://docs.paperinstruments.com/docs/ultramarine
- https://docs.paperinstruments.com/docs/ultramarine/chat-completions
- https://docs.paperinstruments.com/docs/ultramarine/errors
- https://docs.paperinstruments.com/docs/ultramarine/rate-limits
- https://docs.paperinstruments.com/docs/ultramarine/billing
- https://gofastmcp.com/deployment/prefect-horizon
- https://gofastmcp.com/deployment/running-server

Text-only Chat Completions are deliberately used here. The provider supports additional image, streaming and function-call features, but this server does not expose them. Tools for summarizing versus extracting are represented by the operation parameter. Add capabilities only with corresponding validation and live tests.
