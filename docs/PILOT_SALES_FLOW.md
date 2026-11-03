# GreenGrapeMe: B2B Pilot-Inbound-Vertriebsprozess (P0, 02.11.2026)

Die neue GreenGrapeMe-Pilotprozessfunktion schließt die Lücke zwischen vorhandenen Quellen/Inbound-Interessenten und einem **messbaren operativen Sales-Funnel**. Keine zweite Discovery-Engine, kein neuer Agenten-Router, keine Fake-Contact-Authority.

## Geschäftsprozess und Daten-Grenze

Vorhandener bezahlter oder angebotener Pilot wird über `PilotLedger.create` mit `pilot_id` und `offer_id` angelegt. Der hostseitig berechtigte Operator registriert eine **beobachtete**, dokumentierte eingehende Firmenanfrage mit `pilot-inbound`, stabiler `case_id`, Kanal und revisionsfähiger URL/URN des zugrunde liegenden CRM-/Formularereignisses. Die Firma wird dabei nur als `verified_company=False` in die vorhandene `SalesWorkspace`-Opportunity aufgenommen. **Der Kanalname `CRM_INBOUND` oder `WEB_FORM` ist kein Nachweis wirksamer Kontakt- oder Marketingeinwilligung.** Diese muss die zuständige Recht-/Host-Schicht unabhängig prüfen.

Detaillierter, operatorbestätigter Ablauf:
`INBOUND_REVIEW` → `QUALIFIED_REPORTED` → optional `FOLLOWUP_SCHEDULED` / `FOLLOWUP_RECORDED` → `MEETING_HELD_REPORTED` → `PROPOSAL_DELIVERED_REPORTED` → `DEAL_SIGNED_REPORTED`. Ein nicht erfolgreicher Vorgang kann aus einem offenen Schritt auf `CLOSED_LOST` gestellt werden.

Erst **nach tatsächlicher menschlicher Bearbeitung** werden Schritte mit einer neuen `step_id`, `expected_state`, Belegreferenz und Operator-Referenz aufgezeichnet. `FOLLOWUP_SCHEDULED` legt nur einen lokalen Wiedervorlagetermin innerhalb 365 Tagen ab: **kein Versand, keine telefonische Kontaktaufnahme, kein Termin auf einem externen Kalender**. `FOLLOWUP_RECORDED` hält eine vom Operator gemeldete vergangene Aktion fest, beweist aber noch keine rechtliche Berechtigung. Ohne zulässige Kontaktbasis sind ausschließlich passive bzw. bereits rechtmäßig eingehende Workflows erlaubt.

`QUALIFIED_REPORTED`, `MEETING_HELD_REPORTED`, `PROPOSAL_DELIVERED_REPORTED` und `DEAL_SIGNED_REPORTED` schreiben in **derselben DB-Transaktion** die bereits vorhandenen `sales_pilot_events` (LEAD_ACCEPTED, MEETING_HELD, PROPOSAL_DELIVERED, DEAL_SIGNED). Alle werden ausschließlich als **`REPORTED`** gekennzeichnet, nie automatisch `SOURCE_CONFIRMED`. Kein KI-Vorschlag, Formularlabel oder unterschrieben *gemeldeter* Vertrag erzeugt dadurch Umsatz. Etwaige Zahlungen gehören ausschließlich in die unabhängige `PilotLedger`-Quellenabgleichschicht.

## Anwendung – nur vertrauenswürdiger lokaler Operator

```bash
PYTHONPATH=src python -m greengrapeme.cli --db sales.db --tenant <host-tenant-id> \
  pilot-inbound --pilot-id pilot-0001 --case-id inbound-0001 \
  --company "Beispiel GmbH" --channel CRM_INBOUND \
  --evidence-ref urn:crm:verified-source-record-001 --reporter-ref operator-001

PYTHONPATH=src python -m greengrapeme.cli --db sales.db --tenant <host-tenant-id> \
  pilot-step --pilot-id pilot-0001 --case-id inbound-0001 --step-id step-0001 \
  --expected-state INBOUND_REVIEW --to-state QUALIFIED_REPORTED \
  --evidence-ref urn:crm:human-qualification-001 --reporter-ref operator-001

PYTHONPATH=src python -m greengrapeme.cli --db sales.db --tenant <host-tenant-id> \
  pilot-cases --pilot-id pilot-0001
```

Es existiert zusätzlich ein **nur lesender** token-geschützter Localhost-Endpunkt `GET /api/pilot-cases?pilot=...` im bestehenden Tab „Pilot-Wirtschaftlichkeit“. Keine öffentlich zugänglichen HTTP-Writes.

## Abnahme und Grenzen

Tests validieren vollständige berichtete Funnel-Kette mit vier Ledger-Ereignissen, Event-/Schritt-Idempotenz, CAS-Status, Mandantentrennung, unveränderliche Quellen-Fingerprints, Widerruf/Suppression, echte Follow-up-Fälligkeit, Worker-Restart und **0 externe Kundenkontakte**. Nur mit Belegen von CRM/Attendance/Delivery/Contract kann eine unabhängig installierte Provider-Quelle die jeweilige Funnel-Aussage bestätigen. Ein tatsächlicher Kommunikations- oder Buchhaltungsconnector ist hier nicht eingebaut.

**Weiter offen:** authentifizierter produktiver SaaS-Operator/RBAC, rechtliche Einwilligungsprüfung pro Empfänger/Kanal/Zweck, integrierte erlaubte Kommunikations-Effects mit Dispatcher-Reconciliation, echte Kalender-Termine, CRM-Synchronisation, verlässlicher Vertrags-/Zahlungsprovider und drei tatsächlich zahlende Pilotkunden. Diese Implementierung ist ein betriebsfähiger **manuell bestätigter lokaler Sales-Funnel**, noch kein autonomer Kundenabschluss.
