# GreenGrapeMe — SQLite backup, verification and disaster recovery

This runbook describes an **offline operator tool**, not an automatic
backup service or a production high-availability guarantee. It never
contacts StarFruitMe, MangoMe, PlumMe, BlackberryMe, Dittofeed or a
customer. These operations are **global to the database**: one snapshot
contains **all tenants**, pilot financial records, effect/send fences,
audit records and existing installed extension tables. Protect it
accordingly.

## Commands

Run from the package environment with `PYTHONPATH=src` or an editable
package installation. None of the commands requires `--tenant`:

```bash
python -m greengrapeme.cli --db /srv/gg/sales.sqlite db-verify
python -m greengrapeme.cli --db /srv/gg/sales.sqlite db-backup --output /backups/gg-20261104-0645.sqlite
python -m greengrapeme.cli db-restore --backup /backups/gg-20261104-0645.sqlite --output /srv/gg/sales-restored.sqlite
python -m greengrapeme.cli --db /srv/gg/sales-restored.sqlite db-verify
```

`db-verify` checks the SQLite structural integrity, foreign-key integrity,
all mandatory GreenGrapeMe base columns/primary keys, and the schema of every
**initialized** commercial, CRM, Discovery, mission or effect table. It also
checks uniqueness fences for independently confirmed financial receipts and
irreversible provider/effect identities. The JSON result reports
`schema_integrity`, `schema_tables_verified`, and
`uninitialized_optional_tables`: optional feature tables are created lazily
and their absence is **not** treated as proof of feature readiness. A file
whose ordinary SQLite `integrity_check` passes but whose account columns,
composite keys or receipt/send fences are missing now fails validation and
cannot be published by `db-backup` or `db-restore`.

This is **structural** inspection, not online schema migration, complete
business-data reconciliation, third-party permission validation or an
application production-readiness certificate.

`db-backup` uses SQLite's online backup API, rather than copying a live
database file. It captures a consistent set of **committed** transactions,
including transactions still in SQLite WAL mode. It verifies the completed
snapshot, forces standalone DELETE journal mode and publishes it under a
**new** path only. If the path already exists, it fails instead of
overwriting. On supported filesystems it fsyncs the snapshot and its
parent directory; on platforms where directory fsync is unsupported it
cannot promise that durability guarantee. The resulting backup file is
created with owner-only mode on POSIX systems. A SHA-256 digest is reported
for optional external verification; no backup content or secrets are
printed. Backups require enough disk space for another full database.

`db-restore` reads and validates an existing snapshot and publishes a
**new** restored SQLite file. It **never overwrites** the running database
or merges records, jobs, send fences or provider effects. Always use a
different destination path. A restore is not a rollback of already-sent
customer messages or provider actions.

## Operator recovery procedure

1. Restrict access to the encrypted backup destination and verify available
   capacity. Backups contain information from **every** tenant, not just
   the invoking operator.
2. Run `db-verify` on the live source and `db-backup` to a new,
   date-stamped path. An active writer may remain running during backup;
   the SQLite API creates a point-in-time consistent snapshot.
3. Run `db-verify` on the backup. Retain the resulting SHA-256 digest
   and create a second independent, securely stored copy according to your
   retention and disaster recovery policy. This repository does **not**
   provide remote storage or automated retention.
4. For recovery, stop the GreenGrapeMe web app and Discovery worker, and
   stop all other writers to the original database. Restore into a new
   path and verify it before intentionally updating the runtime
   configuration to point to the restored file.
5. Check the tenant, account, pilot, audit and effect counts against
   trusted pre-incident records. Pay special attention to
   `dittofeed_provider_attempts` (irreversible HTTP send fences),
   `dittofeed_pomelo_effects`, `sales_pilot_events`,
   `sales_mission_steps` and `discovery_product_jobs`.
6. Do **not** reset or automatically retry `UNKNOWN`, `DISPATCH_UNCERTAIN`,
   `RUNNING` or `WAITING_APPROVAL` effects. Restoring a backup taken
   **before** an external irreversible action can omit its local send
   fence. Reconcile against the independent PomeloMe/provider ledgers
   before reopening any outbound path. A backup alone cannot prove what
   happened beyond its snapshot timestamp.
7. Restart application processes only after restoring the external
   authorization, consent, credential and tenant-binding controls and
   reviewing unresolved effects with an operator.

## Acceptance evidence and limitations

The test suite exercises online backup with a live WAL writer, multi-tenant
data, pilot commercial terms, irreversible provider-attempt fences, new-path
restore, no-overwrite behavior, invalid and foreign SQLite inputs,
missing/symlink source rejection and tenant-independent CLI commands.

Not implemented here: automated scheduled backups, offsite replication,
retention, real disaster drill timing, encryption/key management,
multi-process restart orchestration, schema migrations, external effect
reconciliation and real-host E2E tests. Until those are operationally
verified, **production release remains blocked**.

## Versioned operational schema upgrade (v1)

Existing pre-auth/partial-feature databases should not be pointed at the
new SaaS service directly. Use the operator-only `db-migrate` command
with a NEW unused output path, after separately backing up the source,
stopping writers for a controlled cutover and reconciling uncertain
external effects:

```bash
PYTHONPATH=src python -m greengrapeme.cli \
  --db /srv/gg/legacy.sqlite db-migrate --output /srv/gg/tenant-data-v1.sqlite
```

The upgrade uses SQLite's committed online backup snapshot (including
WAL), adds the currently known operational module tables, verifies
the complete schema and version ledger, checks that all previous table
row counts are unchanged, then atomically publishes without overwriting
any destination. No business effects/providers are invoked. The
preexisting source database remains **completely unchanged**. This is
a copy-forward baseline migration, **not** a live in-place alteration,
a historical payment reconciliation or a future-version rollback.
The operator must deliberately switch application/worker configurations
to the new database path. The new path must not be used while old
writers continue to create states against the original.
