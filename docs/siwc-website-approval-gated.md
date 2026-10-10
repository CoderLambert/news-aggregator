# SIWC website adaptation (approval-gated)

This branch preserves the existing **local** SIWC flow and prepares an
**approval-gated website mode** for `https://news.lambert.host`.

## Legal and protocol gate

This is **not** an authorization to run hosted ChatGPT plan usage.
OpenAI's SIWC terms (September 29, 2026) require persistent authentication
tokens to remain local and under the user's control, and inference to run in a
runtime the user controls. The ordinary website SIWC guide covers
**identity sign-in only**, not ChatGPT subscription inference.

Do not set `CHATGPT_WEBSITE_PARTNER_APPROVED=1` until OpenAI has **explicitly
approved** the proposed *multi-user, remotely managed token storage and
subscription-backed Responses calls* under a written agreement. Record
the approval reference. An identity-only OAuth client ID is insufficient.

References:
- https://openai.com/policies/sign-in-with-chatgpt-terms/
- https://developers.openai.com/siwc/website
- https://developers.openai.com/siwc/request-client-id
- https://developers.openai.com/siwc/token-sharing-open-source

## Contract-dependent values

After written approval, obtain from OpenAI:
1. Exact website OAuth client ID and approved redirect URI.
2. Scopes **including plan inference** (not merely `openid profile email`).
3. Token endpoint authentication: `none` or `client_secret_basic`; if another
   method is provisioned, implement and review that method before enabling.
4. Explicit permission for remotely hosted per-user credentials and model calls.
5. Confirmation of the Responses and model-discovery endpoints and all applicable
   rate/usage limits. The current code assumes `https://api.openai.com/v1`.

Website OAuth is a **separate registration** from the existing per-user
`dynamic_agent_client` flow. Existing local credentials are never migrated
or silently reused; every website user must authorize this website client.

## Server configuration (after approval only)

In a protected server-side `.env`, replace placeholders with issued values:

```dotenv
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=news.lambert.host
DJANGO_SECRET_KEY=your-existing-stable-django-secret
CHATGPT_TOKEN_ENCRYPTION_KEY=your-existing-stable-encryption-key

CHATGPT_SIWC_MODE=website
CHATGPT_WEBSITE_PARTNER_APPROVED=1
CHATGPT_WEBSITE_APPROVAL_REFERENCE=written-agreement-or-ticket-reference
CHATGPT_WEBSITE_ORIGIN=https://news.lambert.host
CHATGPT_WEBSITE_CLIENT_ID=<APPROVED_OAUTH_CLIENT_ID>
CHATGPT_WEBSITE_REDIRECT_URI=https://news.lambert.host/api/chatgpt-subscription/callback/
CHATGPT_WEBSITE_SCOPES=<EXACT_APPROVED_PLAN_USAGE_SCOPES>
CHATGPT_WEBSITE_TOKEN_AUTH_METHOD=none
CHATGPT_WEBSITE_CLIENT_SECRET=
```

For a `client_secret_basic` registration, set that auth method and supply
the secret **only in a server-side secret store**; never commit or expose it.
The code fails closed without all required values or if debug, wildcard hosts,
wildcard CORS, insecure cookies, or mismatched HTTPS origins are detected.

Leave `CHATGPT_SIWC_MODE=local` and approval flag `0` on all existing local
installations. Local callback and dynamic registration are unchanged.

## Nginx

Add to the **existing** `server_name news.lambert.host` HTTPS server.
Do not start another proxy on port 443 or overwrite the other virtual hosts.

```nginx
# Add this location only when it does not conflict with an existing /api/ rule.
location ^~ /api/chatgpt-subscription/ {
    proxy_pass http://127.0.0.1:9527;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Connection "";
    proxy_read_timeout 150s;
}
```

The callback registered with OpenAI is the **public HTTPS URL**, not the
127.0.0.1 upstream listener. DNS and TLS must be valid. Restrict port 9527 to
loopback or a private Docker bridge; do not publish it to the internet.
A proxy must **overwrite**, not trust, client-supplied forwarding headers.

Set your website's authenticated SPA and API to the same public origin so
the popup's one-time POST handoff and its HttpOnly callback cookie work.

## Safety/compatibility notes

- The browser receives an attempt ID and single-use handoff token, **not**
  OAuth access/refresh/ID tokens or a client secret.
- The website callback sets a Secure, HttpOnly, SameSite=Lax browser-binding
  cookie at exactly `/api/chatgpt-subscription/callback/`. It is expired
  after callback.
- Every pending attempt freezes `oauth_mode`, `redirect_uri`, and
  `token_auth_method`. A changed client or callback before completion
  invalidates the attempt; old dynamic registrations stay `local`.
- Connection queries and model use are scoped by Django user and OAuth mode.
  Refresh uses the stored user's own token; `generation` and database
  refresh leases remain unchanged.
- Website-mode auth, refresh and revocation use the provisioned token-client
  method; there is **no fallback** to API keys on the SIWC request path.
- This feature flag is an **operator declaration**, not proof of approval.
  Do not enable it without an agreement covering this exact deployment.
- Production still requires a stable database and encryption key across
  restarts, secure backups, current OS patching and network controls.
- Public frontend UI describes server-side protected storage only when
  website mode is genuinely enabled.

## Tests and rollout

```bash
# In your existing development environment with dependencies installed
pytest -q backend/api/tests/test_chatgpt_subscription.py \
  backend/api/tests/test_siwc_website_modes.py

cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
cd ..

python backend/manage.py makemigrations --check --dry-run
python backend/manage.py check
```

Use existing migrations/backups workflow before applying migration 0027.
Validate with two separately logged-in Django users (A and B), distinct
ChatGPT users, callback replay, wrong browser, forced disconnect during
refresh, and switching modes. Before activation, only mock-based tests
can run; successful tests do **not** establish OpenAI partner eligibility.
