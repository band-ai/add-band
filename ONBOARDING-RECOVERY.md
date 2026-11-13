# Recovering a Band connection during setup

Follow this investigation only after a relevant failure. Successful onboarding
adds no deployment questions. These instructions take precedence over generic
STOP-on-error instructions for Band HTTP 401/403 responses.

## Investigate before retrying

Pause dependent setup steps and all registrations sharing the rejected key and
destination. Run registrations sequentially; do not try another agent to confirm
an authentication rejection. Identify the operation and actual destination from
configuration and safe status diagnostics. A Band 401/403 can mean incorrect
credentials, insufficient permissions, or a request sent to another deployment.
Do not infer revocation or a company deployment from the error alone. Provider
API errors and ordinary reply timeouts need their own investigation; a numeric
code in an agent message is not evidence of a Band HTTP response.

Reuse what the conversation already establishes. If the usual Band site is
unknown, explain why it helps and ask a free-text question, for example:

> The request to Band was rejected. Your key may be incorrect, or your company
> may use a different Band address. What website do you normally open to use
> Band? You can copy the address from your browser.

Adapt the wording to the evidence and available question tools. Use plain chat
and wait for an answer when the harness cannot collect free text otherwise.
Do not require the user to understand deployment terminology or variable names.

Compare their answer with the actual destination. A browser address is context,
not proof of API hosts or paths. Resolve connection settings from deployment
documentation or existing configuration. Never send credentials to guessed hosts
or invent custom endpoint paths. If details cannot be established, offer:

> Could you send this to your Band administrator? “I am connecting my agent to
> the Band site at [your usual address]. Please provide the supported connection
> settings for this integration and confirm where I should create a user API key
> with permission to register agents.”

Pause until confirmed details are available, then configure them for the user.
If the destination matches or authentication still fails there, help check that
the user key came from that same site and has the required permissions. Acquire
replacement keys through the integration's existing secure local mechanism;
never put them in diagnostics or recovery instructions.

## Apply and resume

Keep one confirmed set of settings through registration, saved configuration,
active process environment, restart, verification and browser links. Exported
settings can override .env; repair both. Keep a known browser address separate
from an API base when they differ. Do not ask a successful user for a browser
address merely to fill a link.

- Tom & Jerry: set BAND_REST_URL and BAND_WS_URL in the project .env and active
  invocation environment. Registration uses BAND_BASE_URL=BAND_REST_URL. Restart
  affected agents and run the real reply checker from the project directory with
  the confirmed REST URL explicitly in its environment.
- Hermes: repair BAND_BASE_URL and platforms.band.extra.base_url as applicable,
  including stale environment overrides. The runtime derives HTTPS/WSS and fixed
  paths from the host/port; independent endpoints or custom paths are unsupported.
- NanoClaw: repair BAND_BASE_URL in .env and the active environment, including
  stale supported legacy aliases. Use that confirmed host for OneCLI matching and
  propagate it to runtime/container and optional MCP configuration. The runtime
  derives REST origin and its fixed socket path; independent paths are unsupported.
- OpenClaw: set the existing account's restUrl and wsUrl under
  channels.openclaw-channel-band.accounts.<agent-id>. Registration uses
  BAND_BASE_URL; BAND_WS_URL can supply the confirmed socket URL. Merely exporting
  variables or rerunning the bootstrap does not repair an existing account.

Explicitly clear/replace stale custom settings when returning to the cloud.
For unsupported topology, ask the administrator for compatible settings rather
than inventing configuration or changing SDK behavior.

Preserve completed registrations and their credentials scoped to the deployment
that created them. Retry only missing work after the cause is resolved. If a POST
may have succeeded but credentials were not retained (including interruption),
check existing agents in that deployment's UI/configuration before creating any
more. Do not assume cleanup ran. Do not automatically delete agents or promise
lost-key recovery. If the confirmed destination changes, preserve/report old
registrations separately; never send their credentials to the new deployment.
On cancellation, stop dependent actions and retain known state for reconciliation.

After repair, restart affected processes and verify a real reply. A successful
registration or connected socket alone is not completion. Report cleanup problems
without obscuring the primary outcome.
