# G4 Closer: independently confirmed offers and contracts (schema v5)

GreenGrapeMe now records one immutable approved offer for each existing CRM case. Each offer snapshots the pilot's agreed offer ID, EUR monthly and setup fees, customer opportunity source hash, proposal document reference and catalog version. Prices cannot silently change after preparation.

## Domain flow

1. SalesContracts.prepare(...) checks the delivered CRM proposal state, pilot price, exact opportunity provenance and suppression; it stores PREPARED without any customer contact or external action.
2. SalesContracts.approve(..., approval=IndependentOfferApproval) asks an independently authenticated host-owned catalog/authorization source to confirm the exact terms hash, current product price, approver authority and approval receipt. The record becomes APPROVED.
3. SalesContracts.reconcile(..., source=IndependentSignedContract) requires an independent, read-only verification of the executed agreement against the same terms hash, signer, case and approval receipt. A confirmed signature updates the contract, CRM case, CRM transition history and existing PilotLedger in ONE SQLite transaction.

An accepted signed deal writes a SOURCE_CONFIRMED DEAL_SIGNED ledger event with provider_kind=CONTRACT and a unique independent provider receipt. It does not infer payment, consent or calendar attendance. Repeated confirmation reads return the existing signed record; a mismatched signer or reused receipt is rejected.

## Architecture and limits

SalesContracts is a host-side domain port, not a new CRM or a signature provider. There is no browser-write endpoint capable of approving offers or signing agreements. Caller-created URNs, AI messages and CRM self-reporting cannot by themselves become independent proof.

The two injected trusted host protocols must be implemented by a connector using a real product catalog and genuine e-signature service credentials (for example an existing enterprise signing service). The signature connector is required to check executed document bytes/hash and signer authority, not merely echo the submitted request. The host must bind the correct legal party, current pricing approvals, contract template revision and provider receipt.

Schema v5 is initialized by explicit fresh-database bootstrap; older databases use copy-forward migration. Backup verification checks the one-contract-per-case constraint and unique approval/signature receipts; existing sales and calendar histories survive the migration.

## Tests and remaining requirements

Local tests exercise frozen pricing, proof identity mismatches, lost/replayed receipts, suppression and source drift, signature source conflicts and the atomic CRM+ledger transition. No customer was contacted and no live signature was executed. Actual host authentication/catalog integration, provider signature document verification and complete G1–G5 end-to-end acceptance are still required before production readiness can be declared.
