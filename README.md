# openimis-be-access_request_py

openIMIS Backend **Access Request / Account Provisioning** module for the
TASAF MIS (CoreMIS / openIMIS) implementation.

A public, self-service page lets a person **without a login** apply for a new
account (or request activation of an existing one). Requests flow through a
transparent, signed **two-level approval** (Manager -> ICT) and, on final approval,
a `core` interactive user is created/reactivated and credentials are emailed to the
applicant.

> **Full design & diagrams:** see [`docs/00-overview.md`](docs/00-overview.md).
> This module ships **Phase 1**; Phase 2 (bulk requests, SLA/escalation, PKI
> signatures, offboarding, …) is designed-for but not implemented — see
> [`docs/00-overview.md#9-scope--phase-2`](docs/00-overview.md).

## What it does

- **Public landing page** — hero ("Create Your TASAF MIS Account") + "Simple
  3-Step Process" cards + an application wizard, all **unauthenticated**.
- **Untrusted submit endpoint** — `AllowAny` DRF view (empty
  `authentication_classes`), per-IP rate limit + honeypot + pluggable CAPTCHA;
  records an inert `AccessRequest`, grants nothing.
- **Curated profiles** — applicants pick a friendly label, never a raw `core.Role`;
  staff map profile to real Role(s) at approval, validated against the approver's
  own authority.
- **Two-level, signed approval** — Manager then ICT, via the generic approval engine.
- **Provisioning** — calls `core` `CreateUserMutation` (or reactivates an existing
  user), then emails username + set-password link.

## Models

`AccessRequest`, `AccessProfile` — both extend
`core.models.HistoryModel` (UUID PK, soft delete, audit, `json_ext`), each with a
`*Mutation` journal table.

## Rights (module `23`)

`230101` Search · `230102` View detail · `230201` Manager approval step ·
`230202` ICT approval step · `230301` Manage profiles/mapping. **Submitting is
public — no right required.** Defaults in
`access_request/apps.py::DEFAULT_CONFIG`, overridable via
`core.ModuleConfiguration`. Granted to the IMIS Administrator role on migrate.

## Install

```bash
pip install -e ../openimis-be-access_request_py
python manage.py makemigrations access_request
python manage.py migrate
```

Register in `openimis-be_py/openimis.json` and `modules-requirements.txt`
(`-e ../openimis-be-access_request_py`).

## GraphQL & endpoints

Queries: `accessRequest`, `accessProfile`.
Mutations: submit is via the public DRF endpoint; staff approval decisions are made
through `openimis-be-approval_py`; this module owns profile CRUD and
`provisionAccessRequest`.
Public submit / status via DRF endpoints under `/api/access_request/...`.

## Developer Guide

Start with `access_request/models.py` for the public application and profile
models, `access_request/services.py` for submit/provisioning logic, and
`access_request/approval_adapter.py` for the handoff from the approval engine.

The approval rows are intentionally not stored in this module. The flow is seeded
by `openimis-be-approval_py` as `ACCESS_REQUEST_ACCOUNT`; final approval moves the
request to `ICT_APPROVED`, then provisioning creates or reactivates the core user.

When changing permissions, keep the `23xxxx` rights in `access_request/apps.py`,
the frontend constants, and any approval-flow `required_right` values aligned.
Run `python manage.py makemigrations access_request` only for real schema changes.
