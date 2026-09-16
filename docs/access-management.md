# Access and membership management

## Sign-in flow

GRP provides an access-request registration screen only for people with an existing SIG/SERVIR account. It never creates a SIG account or stores a password. SERVIR authenticates the person through OIDC; GRP then authorizes the verified identity from its own records.

1. The applicant selects registration and authenticates with their existing SERVIR account.
2. An unknown verified email is denied entry and recorded as `identity_link_denied`, which becomes the pending request. The short-lived MCP access token is not stored.
3. A Platform Admin reviews the protected workspace queue and assigns a Hub plus `planner` or `admin` role.
4. The person returns to SERVIR sign-in. GRP links the issuer/subject identity and creates a signed session.
5. Every protected request reloads the account and active memberships, so disabling access takes effect without waiting for session expiry.

This first slice exposes the notification in the protected Platform Admin workspace, backed by the audit queue. It does not send email. Do not add a mailing integration without an approved sender, recipient policy, and operational owner.

## SIG OAuth client configuration

A SIG account is necessary but not sufficient. GRP discovers the authorization server from `SIG_MCP_BASE_URL` and requests the MCP resource audience. Register a callback-specific public PKCE client once:

```bash
python -m grp.oauth register-client \
  --redirect-uri https://staging-risk-servir.adpc.net/api/v1/auth/callback \
  --client-name "ADPC GRP staging" \
  --output-file .local/staging_servir_client_id
```

Copy the resulting non-secret client ID into `SERVIR_AUTH_CLIENT_ID` in `/srv/grp/app/.env`. `SERVIR_AUTH_ISSUER` is an optional pin and otherwise comes from protected-resource discovery. A public client needs no client-secret file. If SIG provisions a confidential client instead, write its secret only to `/srv/grp/secrets/servir_auth_client_secret`, owned by root with mode `0600`. Never send secrets through Git or chat.

## Membership tables

| Table | Purpose | Key rule |
|---|---|---|
| `hub` | ADPC/SERVIR tenant boundary | Unique stable `code`; active or closed |
| `app_user` | GRP authorization account | Lowercase unique verified email |
| `external_identity` | SERVIR issuer/subject link | Unique `(issuer, subject)`; never stores tokens |
| `hub_membership` | User-to-Hub role mapping | Unique `(hub_id, user_id)`; `planner` or `admin` |
| `audit_event` | Denials and access changes | Append-only operational evidence |

“Hub Expert” is a SIG designation, not a GRP role. Map it to `planner` unless the person must administer Hub membership.

## First staging assignment

Run these from the VM after deployment. Enter emails in the shell; never write them into Git or `.env`.

```bash
cd /srv/grp/app
read -r -p "Platform Admin email: " GRP_ADMIN_EMAIL
sudo docker compose --env-file .env -f deploy/compose.yml run --rm --no-deps api \
  python -m grp.admin bootstrap-platform-admin --email "$GRP_ADMIN_EMAIL"
sudo docker compose --env-file .env -f deploy/compose.yml run --rm --no-deps api \
  python -m grp.admin ensure-hub --actor-email "$GRP_ADMIN_EMAIL" --code adpc --name "ADPC Hub"
```

After the user attempts sign-in, the Platform Admin can assign the request from the workspace. These commands provide a server-side fallback:

```bash
sudo docker compose --env-file .env -f deploy/compose.yml run --rm --no-deps api \
  python -m grp.admin list-access-requests
read -r -p "Member email: " GRP_MEMBER_EMAIL
sudo docker compose --env-file .env -f deploy/compose.yml run --rm --no-deps api \
  python -m grp.admin assign-member --actor-email "$GRP_ADMIN_EMAIL" \
  --email "$GRP_MEMBER_EMAIL" --hub-code adpc --role planner
unset GRP_ADMIN_EMAIL GRP_MEMBER_EMAIL
```

Commands are idempotent for identical input and write audit events for changes.
