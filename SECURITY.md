# Security

## Reporting a vulnerability

Please open a [private security advisory](https://github.com/arhanbarve/letterboxd-recs/security/advisories/new)
rather than a public issue. I'll respond as quickly as I can — this is a
personal project, so expect days rather than hours.

## What this project protects, and what it doesn't

Data is scoped per Letterboxd username. The first import of a username claims
it and mints an access code; every later read or write for that username has to
present the code back. Only the SHA-256 of a code is stored, so the database
never holds a working credential.

That is deliberately a bearer token, not an identity system. Specifically:

- Anyone holding a code has full access to that username's imported ratings,
  taste profile, and recommendations.
- A lost code is unrecoverable by design. Import under a different username to
  start over.
- There are no accounts, passwords, sessions, or email verification.
- Rate limits are per client IP and held in process, so they reset on redeploy
  and are shared by everyone behind one NAT.

It is built for a small trusted group sharing one deployment. Treat it as such.

## Handling of personal data

A Letterboxd export contains your email address in `profile.csv`. The importer
reads only `ratings.csv`, `watched.csv`, and the `Username` column of
`profile.csv` — the email is never parsed, stored, or logged.

Uploads are capped at 25 MB compressed and 200 MB uncompressed, with the
declared size checked from the zip header before anything is unpacked.

## Dependencies

TMDB and OMDb API keys are read from the environment and never committed. If
you deploy this yourself, set them as secrets on your host; `render.yaml` marks
them `sync: false` so they are never read from the repo.
