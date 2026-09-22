# Security policy

## Reporting a vulnerability

Do not open a public issue for a security problem.

Use GitHub's private reporting instead: **Security → Report a vulnerability** on
[this repository](https://github.com/ettoreboy/unfold/security/advisories/new). If that is not
available to you, email **ettore@amphoralogistics.com** with `[unfold security]` in the subject.

Expect a first reply within 72 hours. This is a hackathon project maintained in spare time, so
there is no paid triage rota and no bug bounty.

## Scope

Unfold is a Chrome extension plus a FastAPI backend you run yourself. There is no hosted service,
no user account and no database. The interesting parts of the attack surface are:

| Area | What matters |
| --- | --- |
| `backend/services/link_service.py` | Fetches URLs from search results. Server-side request forgery, redirect handling, response size caps. |
| `backend/services/nebius_service.py` | Sends post text to a third-party model. Prompt injection from a hostile post, key handling. |
| `extension/content/` | Injected into `x.com`. DOM injection, Shadow DOM escape, anything that could read a logged-in session. |
| `.env` handling | API keys for Nebius, Brave, Gemini, Galtea and SLNG live here and must never reach the repo or a log line. |

Out of scope: the accuracy of an analysis, a model returning a wrong verdict, rate limits on a
third-party API, and anything that needs an attacker to already control your machine.

## Keys and secrets

`.env` is gitignored and has never been committed. `.env.example` holds every variable name with
an empty value; CI fails if a credential in it is non-empty, and fails if `.env` is ever staged.

If you believe a key has leaked, rotate it in the provider console first, then tell us. Rotating
is always faster than a history rewrite.

## Supported versions

The `main` branch only. There are no release branches and no backports.
