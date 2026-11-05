# Security

Controls that are implemented and tested, followed by the gaps that remain. The platform holds
public, anonymised Olist data. The sensitive assets are user accounts, the app schema, the
database credentials and the LLM API key.

## Threat model (summary)

| Threat | Control | Where |
|---|---|---|
| Stolen or forged tokens | Short-lived JWT access tokens (15 min, HS256 with a ≥ 32-character secret, `alg` pinned). Refresh tokens are opaque, stored hashed, rotated on every use, and reuse revokes the whole session family | `backend/app/core/security.py`, `services/auth_service.py`, tests in `test_auth.py` |
| Password guessing | Argon2 hashes, a 12-character minimum with mixed case and a digit, a login rate limit (10/minute), and failed logins audited | `schemas/auth.py`, `core/rate_limit.py` |
| Privilege escalation | RBAC (viewer < analyst < admin) on every route, a full role × endpoint test matrix, admin-only role changes, and denials audited | `api/deps.py`, `test_api.py` |
| SQL injection | Parameterised SQL everywhere. Query parameters validated by pattern (months, states, ids). The assistant's SQL goes through a parser allowlist (single `SELECT`, `marts`/`ml` only, no system functions) | `repositories/`, `assistant/sql_guard.py`, `test_sql_guard.py` |
| Over-privileged database access | Separate roles. `analytics_ro` can only `SELECT` from `marts`/`ml`, in read-only transactions with a 15 s timeout; `app_user` owns only the `app` schema; `etl_user` builds the warehouse. Postgres listens on localhost only | `infrastructure/postgres/init_roles_schemas.sql` |
| Prompt injection / LLM misuse | The model gets read-only tools filtered by role, never raw database access. Free-text review columns are blocked. Tool results are framed as data. Loop and token limits are bounded. Answers are rendered as plain text. Every question is logged | `assistant/`, [assistant.md](assistant.md) |
| XSS / clickjacking | React escapes output, and no HTML from the API or the model is rendered. The API sends `default-src 'none'`; the web server sends a strict CSP (`script-src 'self'`, `frame-ancestors 'none'`), `nosniff`, `X-Frame-Options: DENY` and `no-referrer` | `core/observability.py`, `infrastructure/docker/web/security-headers.inc` |
| Token theft from the browser | The access token is kept in memory only; the refresh token is in sessionStorage (cleared when the tab closes) | `frontend/src/services/api.ts` |
| Abuse / cost | Per-client rate limits (default 120/minute, auth 10/minute, assistant 20/minute). Request body size capped at 64 KB in nginx | `core/rate_limit.py`, `nginx.conf` |
| Secrets in the repo | `.env` is git-ignored and excluded from Docker build contexts. The `detect-private-key` pre-commit hook runs locally; gitleaks runs in CI | `.gitignore`, `.dockerignore`, `.pre-commit-config.yaml`, CI |
| Vulnerable dependencies | pip-audit on the locked runtime dependencies, npm audit on production dependencies, Trivy on both images (fixable HIGH/CRITICAL fail the build), Dependabot weekly | `.github/workflows/ci.yml`, `.github/dependabot.yml` |
| Container breakout / lateral movement | Non-root users (uid 10001, nginx-unprivileged), read-only root filesystems, `cap_drop: ALL`, `no-new-privileges`, a memory limit on the API, published ports bound to 127.0.0.1, models and registry mounted read-only | `docker-compose.yml`, Dockerfiles |
| Untrusted model files | Models are serialised with skops with an explicit list of trusted types. Only models produced by the training scripts are loaded | `ml/train_customer_models.py` |
| Repudiation | `app.audit_log` records logins, refreshes, role changes, authorization denials and assistant tool or SQL denials. `app.assistant_log` and `app.prediction_log` record usage. Request ids appear in every response, log line and error | `services/audit.py` |

## Scan results (2026-11-05, local)

| Scan | Scope | Result |
|---|---|---|
| pip-audit 2.9.0 | 443 locked runtime packages (backend + ml groups) | No known vulnerabilities |
| npm audit | Production dependencies | 0 vulnerabilities |
| npm audit | All, including dev | 1 moderate (minimatch ReDoS via eslint / typescript-eslint, lint-time only). npm's suggested fix is a breaking eslint downgrade, so it is not applied; Dependabot will pick up the upstream fix |
| bandit 1.8.6 (medium+) | `backend/app`, `ml`, `data_engineering` | 1 finding (B310 `urlopen` in the dataset downloader), fixed by refusing non-HTTPS URLs |
| gitleaks, Trivy | Repository history, images | Not run locally (not installed; Docker unavailable on this machine). They run in CI |

## Known gaps

- **No TLS termination** in the compose stack. Ports are bound to localhost; a real deployment
  needs a TLS proxy and then `Strict-Transport-Security`.
- The refresh token is readable by JavaScript (sessionStorage). An httpOnly, SameSite cookie
  flow would be stronger, but would need CSRF protection.
- Rate limits are in memory and per process. Several replicas would need Redis.
- No account lockout or MFA, and no per-user LLM token budget.
- Secrets come from environment variables. There is no secret manager or rotation procedure.
- The audit log has no retention policy and is not shipped off the host.
- The CI workflow has never run: the repository has no remote yet. See
  [deployment.md](deployment.md).
