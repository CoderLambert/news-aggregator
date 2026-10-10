# ChatGPT subscription authorization modes

The subscription integration has two distinct contexts. `local_oss` is the existing development-only flow, whose callback remains `http://127.0.0.1:9527/api/chatgpt-subscription/callback/`. It uses the current dynamic registration and `none` token-endpoint authentication behavior. Production rejects this mode. `disabled` rejects subscription network operations with HTTP 403. `website` remains fail-closed with HTTP 503 until the required external approvals exist.

Website authorization is **EXTERNAL_BLOCKED**. The required hosted OAuth/provider approval and hosted subscription-plan usage approval are both unapproved. No website client ID, client secret, approved privacy-policy URL, exact hosted redirect contract, scope/resource set, or provider contact/policy has been established here. This implementation does not infer those values or make a real authorization or provider request. Both website approval states remain `false`; real website OAuth acceptance is **NOT_RUN**.

Each local authorization attempt records a canonical snapshot of its non-secret protocol configuration and a SHA-256 fingerprint. Handoff and callback check the current mode/configuration against that snapshot before consuming the one-use ticket or authorization state. The callback also requires the same active NewsHub user and session that created the attempt. A changed discovery issuer or endpoint prevents token exchange. Old pending attempts without a snapshot are marked failed with `config_changed` by migration 0029; terminal attempts are preserved.

The callback uses the standard Django session authentication flow. Its binding cookie is host-only, HttpOnly, SameSite=Lax, limited to the callback path, and expires after ten minutes. On local HTTP it is not marked Secure. Callback success and handled failure both clear it using the same path and no Domain attribute.

Verification for this change is limited to isolated offline tests with mocked discovery/token/JWKS responses. No real OAuth, paid provider API, or website acceptance test has been run.
