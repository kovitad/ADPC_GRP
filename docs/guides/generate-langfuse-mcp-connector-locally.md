# Generate the Langfuse MCP connector locally

## Purpose

This local browser utility generates the Basic Authorization value needed to connect an approved
Claude user to the **GRP Evaluation** project's Langfuse MCP server. It does not test the keys,
contact Langfuse, or store either key.

The project API key permits access to project data and may expose write/delete tools. Use this
utility only when an authorized administrator has approved an individually managed connector.
Prefer a centrally managed connector with restricted tools for normal users.

## Open the utility

Start the GRP application locally through the supported development workflow, then open:

```text
http://127.0.0.1:8000/langfuse-mcp-connector.html
```

The form remains disabled unless its origin is `localhost`, `127.0.0.1`, IPv6 loopback, or a local
file. Its Content Security Policy denies network connections. Do not bypass this restriction or use
a copy hosted on another domain.

## Generate the value

1. Obtain the **GRP Evaluation** public and secret project keys through ADPC's approved
   secret-delivery process.
2. Enter the matching `pk-lf-…` and `sk-lf-…` values.
3. Select **Generate and copy Authorization value**.
4. The utility copies `Basic <base64(public-key:secret-key)>` without displaying it, then clears
   both fields.
5. In Claude, add a custom connector with these settings:

   | Setting | Value |
   |---|---|
   | Connector name | `grp-langfuse` |
   | MCP URL | `https://langfuse-risk-servir.adpc.net/api/public/mcp` |
   | Authentication | **No sign-in** |
   | Request-header name | `Authorization` |
   | Request-header value | Paste the generated clipboard value |
   | Transport | Automatic |

6. Save the connector and immediately overwrite the clipboard with harmless text.

The encoded Basic value is still a secret. Never place either key or the generated value in chat,
email, screenshots, documents, shell history, logs, or Git. Revoke and replace the project key if
it is exposed.

## First test

Start with a read-only health check:

```text
Use the grp-langfuse connector in read-only mode. Call getHealth and report whether the server is
healthy. Do not create, update, or delete anything.
```

Initially allow only required read operations. Deny tools beginning with `create`, `update`,
`delete`, `upsert`, `batchUpsert`, `attach`, `detach`, or `submit`. Never connect Production
credentials through this procedure.
