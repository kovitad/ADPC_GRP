# Connect Claude to the GRP Langfuse MCP server

## Purpose

This guide connects an approved Claude user to the **GRP Evaluation** project through Langfuse's
native MCP server. Start with read-only use: health checks, observations, metrics and dashboards.
Do not connect Production credentials through this procedure.

## Important security boundary

The Langfuse project API key grants access to project data and includes write/delete tools. Normal
users should not receive or exchange the public/secret key pair. The recommended approach is for
an authorized administrator to provision a centrally managed connector and restrict its allowed
tools.

If an individually managed connector is approved:

- obtain the Evaluation key through ADPC's approved secret-delivery process;
- never send the key or encoded header through chat or email;
- never put it in screenshots, Word documents, Git or shell history;
- do not use a Google OAuth client, Gmail App Password or Langfuse website password; and
- revoke and replace the project key immediately if it is exposed.

## Connection details

| Setting | Value |
|---|---|
| Connector name | `grp-langfuse` |
| MCP URL | `https://langfuse-risk-servir.adpc.net/api/public/mcp` |
| Authentication | **No sign-in** |
| Request-header name | `Authorization` |
| Request-header value | `Basic <base64(public-key:secret-key)>` |
| Transport | Automatic (streamable HTTP) |
| Initial project | GRP Evaluation |

The encoded Basic value remains a secret even though it is Base64 text.

## Generate the header safely on Windows

Use this local Python command. It asks for the credentials without displaying the secret, creates
the complete Authorization value, and copies it directly to the Windows clipboard without printing
it.

```powershell
@'
from base64 import b64encode
from getpass import getpass
import subprocess

public_key = input("Langfuse Evaluation public key: ").strip()
secret_key = getpass("Langfuse Evaluation secret key: ").strip()
if not public_key.startswith("pk-lf-") or not secret_key.startswith("sk-lf-"):
    raise SystemExit("The Langfuse project keys do not have the expected format")
header = "Basic " + b64encode(f"{public_key}:{secret_key}".encode()).decode()
subprocess.run(["clip.exe"], input=header, text=True, check=True)
print("Authorization value copied to the clipboard; no credential was printed.")
'@ | python -
```

After the connector is saved, overwrite the clipboard by copying harmless text.

## Add the Claude connector

1. Open Claude's connector settings and choose **Add custom connector**.
2. Enter the connector name `grp-langfuse`.
3. Enter the MCP URL exactly as shown above.
4. Under **Authentication**, select **No sign-in**.
5. Do not select **Sign in now**, **Register automatically**, **Use Claude's published identity**,
   or **Use your own OAuth client**. Those options require OAuth, while this Langfuse endpoint uses
   project-key Basic authentication.
6. Under **Request headers**, choose **Add header**.
7. Enter `Authorization` as the header name.
8. Paste the generated clipboard value into the header-value field.
9. Leave the transport setting automatic.
10. Save the connector and overwrite the clipboard.

Claude stores the configured header securely. Do not reopen or copy it except during an approved
key rotation.

## First read-only tests

Begin every test by telling Claude to use read-only tools and not modify anything.

### Health

```text
Use the grp-langfuse connector in read-only mode. Call getHealth and report whether the server is
healthy. Do not create, update or delete anything.
```

### Dashboard

```text
Use grp-langfuse to list dashboards. Find “GRP AI at a glance” and explain its widgets in plain
language. Read only.
```

### Recent activity

```text
Using grp-langfuse, list the 10 newest observations from the development environment. Summarize the
workflow, model, token usage, duration, level and estimated cost. Do not expose identifiers and do
not modify anything.
```

### Privacy check

```text
Inspect one recent GRP AI observation using grp-langfuse. Confirm whether prompts, answers, email
addresses or credentials were stored. Do not reproduce identifiers and do not modify anything.
```

## Tool permissions

For initial use, allow only these read operations:

```text
getHealth
listObservations
getObservation
getObservationFieldSchema
getObservationFilterSchema
getObservationFilterValues
queryMetrics
getMetricsSchema
listDashboards
getDashboard
listDashboardWidgets
getDashboardWidget
listModels
listScores
getScore
```

Deny tools beginning with `create`, `update`, `delete`, `upsert`, `batchUpsert`, `attach`, `detach`
or `submit` unless an approved task specifically requires the change. MCP access must not be used
to alter Production.

## Troubleshooting

### Claude reports an OAuth registration failure

Example:

```text
Couldn’t register with grp-langfuse’s sign-in service
```

The connector was configured with OAuth. Return to its settings, select **No sign-in**, and provide
the `Authorization` request header. Do not add an OAuth Client ID.

### Unauthorized or 401 response

Confirm that:

- the complete header starts with `Basic `;
- the public and secret keys belong to the same Evaluation project;
- the key has not been revoked; and
- no spaces or line breaks were inserted into the encoded value.

Do not paste the header into support messages. Ask the key custodian to rotate it if its handling is
uncertain.

### Connected but no observations appear

- Select the `development` environment or **All**.
- Use a recent time range.
- Run a new GRP Platform **Test AI call**.
- Remember that calls rejected before the Langfuse v4 integration were not recreated.

### Cost is blank

Blank cost means Langfuse does not have recognized pricing for the exact model identifier. It does
not mean the AI call was free. GRP's database remains authoritative for user allowance, and the
provider invoice remains authoritative for financial cost.

## Removal and rotation

When access is no longer required:

1. Remove or disable the Claude connector.
2. Notify the Langfuse project-key custodian.
3. Revoke and replace a shared project key when a custodian or authorized user leaves the role.
4. Update every approved connector that depended on the rotated key.
5. Record the rotation through ADPC's normal operational process without recording the key value.

## Related guidance

- [How Langfuse works with GRP](how-grp-langfuse-works.md)
- [ADR-0069: Langfuse v4 uses OTel ingestion](../adr/0069-langfuse-v4-uses-otel-ingestion.md)
- [Official Langfuse MCP documentation](https://langfuse.com/docs/api-and-data-platform/features/mcp-server)
