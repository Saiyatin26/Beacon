# OpenSpec — invariant provenance

This directory is managed by the OpenSpec CLI. Run `npx openspec@latest init`
here once to set it up properly (creates `openspec/AGENTS.md` and project
config).

`backend/mining/spec_provenance.py` writes a `changes/<invariant_id>/proposal.md`
here for every invariant that graduates in Stage 2 — giving a git-tracked,
human-readable trail from raw evidence to enforced oracle (architecture doc
Section 2 and Section 8's claim-drafting note: this is the *embodiment* of
"an auditable versioned specification artifact," not the novelty claim itself).

Once `openspec init` has run, `openspec/changes/` will start filling up
automatically as you run the mining pipeline against real invariants.
