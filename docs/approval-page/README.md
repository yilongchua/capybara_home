# Approvals Page Removal

This folder documents the removal of the `/workspace/approvals` UI tab and the
rationale for keeping the underlying approval backend in place.

- [removal-impact.md](removal-impact.md) — full impact analysis (page, hooks,
  API, backend, cross-feature coupling) that informed the decision.
- [decision.md](decision.md) — the chosen option (A: remove page, keep
  backend), why no UI migration to the Scheduled Pipeline page was required,
  and the followup risks to watch.
- [changes.md](changes.md) — concrete list of files changed and why.
- [followups.md](followups.md) — open items: when the backend approval system
  could be retired entirely, what would have to move first.
