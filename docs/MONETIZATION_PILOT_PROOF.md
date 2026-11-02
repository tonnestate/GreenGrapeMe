# GreenGrapeMe – monetarisierungsfähiger Pilot-Nachweis (P0)

**Implementiert:** Fachliche Pilotakte, dauerhaft gespeicherte Ereignisbelege, Vertriebs-Funnel-Metriken, Trennung zwischen gemeldeten und quellbestätigten Ergebnissen, lesendes lokales Pilot-Dashboard. **Nicht implementiert:** Zahlungsempfang, Billing, Bank-/Accounting-Adapter, tatsächlicher Umsatznachweis, autonomer Outbound oder SaaS-Onboarding.

## Ziel

Drei unabhängig zahlende B2B-Pilotkunden sind eine kommerzielle Prüfbedingung, nicht eine erfundene Kennzahl. Jeder Pilot hält sein zu prüfendes Angebot und die angebotenen Gebühren als **geplante Konditionen**, nicht als Zahlung oder ARR/MRR. Der Scorecard-Kern trennt:

- Produkt-Preisbereitschaft: eine tatsächlich unabhängige Plattform-Zahlungsbestätigung gegen Pilot-ID und Rechnung/Provider-Referenz.
- Effekt auf Kundengeschäft: Leadannahme, nachweislich stattgefundenes Meeting, zugestelltes Angebot, Vertrag, tatsächlich vereinnahmte Kundenzahlung.
- Kosten: separat bestätigte externe Providerkosten; **ohne Kosten-Vollständigkeitsnachweis keine Profitabilitätsbehauptung**.
- Attribution: Eine Kundenzahlung beweist nicht, dass GreenGrapeMe die Zahlung zusätzlich verursacht hat. Baseline, Kontrollgruppe oder unabhängige Prüfung sind separate Release-Gates.

## Implementierte Datenverträge

Die Tabellen sales_pilots und sales_pilot_events sind tenantgebunden; die Daten bleiben Sales-Fachprojektion in derselben lokalen SQLite-Akte. Es gibt keine neue Golden-Company-Masterdatenbank.

Zulässige Events: LEAD_ACCEPTED, MEETING_HELD, PROPOSAL_DELIVERED, DEAL_SIGNED, CUSTOMER_PAYMENT_RECEIVED, PLATFORM_PAYMENT_RECEIVED, PROVIDER_COST_INCURRED. Erstere betreffen eine im gleichen Mandanten und für das gleiche Angebot existierende Opportunity; Plattformzahlungen und Providerkosten dürfen keinem Kundenkonto als Prospect-Conversion zugeordnet werden.

Alle frisch aufgenommenen Events beginnen als REPORTED. Eine vom Operator eingetragene Beleg-URL/URN ist **nur eine Referenz, kein überprüftes Faktum**. source-confirmed wird allein über den nicht öffentlich exponierten Aufruf PilotLedger.reconcile(..., source=IndependentEvidenceSource) möglich. Dieser verlangt einen unabhängig vom Event abgefragten Provider-Receipt, erlaubten Provider-Typ, identische Event-Art, Beleg-ID, EUR-Währung und Cent-Betrag. Receipt-IDs sind je Tenant einzigartig, damit dieselbe Zahlung nicht zwei Events bestätigen kann. Der erforderliche vertrauenswürdige Real-Provider-Adapter ist ein weiterer Integrationsschritt und **noch nicht vorhanden**. GitHub-Tests verwenden eine rein künstliche Quelle und erzeugen keinerlei reale Umsatzbelege.

Alle Geldwerte werden in **integer EUR cents** gespeichert; keine Gleitkomma-Berechnungen für Zahlungseingänge. Eine Änderung derselben Pilot- oder Event-ID mit abweichenden Konditionen wird abgewiesen. Event-Zeiten sind UTC-normalisiert. Der Operator-CLI-Anbieter muss bereits im vertrauenswürdigen Host-Kontext laufen; Browserzugriffe sind lesend, Token-geschützt und nur über localhost erlaubt.

## Bedienung (nur autorisierter lokaler Operator)

Vorab: vorhandene GreenGrapeMe-Installation, Host-spezifische TENANT- und DB-Zuordnung und tatsächlich genehmigter Pilotvertrag.

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant <tenant> --db sales.db \
  pilot-create --pilot-id pilot-001 --offer-id <offer> --label "Pilot 1" \
  --monthly-fee-cents 79000 --setup-fee-cents 99000

PYTHONPATH=src python -m greengrapeme.cli --tenant <tenant> --db sales.db \
  pilot-record --pilot-id pilot-001 --event-id payment-001 \
  --kind PLATFORM_PAYMENT_RECEIVED --amount-cents 79000 \
  --evidence-ref urn:accounting:external-record-1 --reporter-ref operator-001

PYTHONPATH=src python -m greengrapeme.cli --tenant <tenant> --db sales.db \
  pilot-report --pilot-id pilot-001
```

Wichtig: Der zweite Schritt berichtet zunächst lediglich einen **ungeprüften** Zahlungsvorgang; die bestätigten Plattformzahlungen bleiben **0 €** und pricing_validation bleibt NOT_PROVEN. Ohne wirklichen Accounting-/Bank-Quellenadapter wird keine Zahlung hochgestuft. Der Preis von 790 € ist ein beispielhafter zu testender Angebotspreis, **kein nachgewiesener GreenGrapeMe-Vertragspreis**.

## Oberfläche und Testabnahme

GET /api/pilots und GET /api/pilot?id=… sind tenantgebundene, authentifizierte, **read-only** lokale Endpunkte. Der bestehende Discovery-Arbeitsplatz besitzt einen zusätzlichen Tab "Pilot-Wirtschaftlichkeit", ohne Zahlungsfunktion und ohne neue Wrapper-/Designkonzepte. Event-Aufnahme, Pilot-Vertrag und unabhängige Belegprüfung dürfen nicht als unkontrollierte HTTP-Writes exponiert werden.

Der Bericht zeigt geplante Konditionen, Anzahl unbestätigter und quellbestätigter Events, ausdrücklich getrennte Kunden-/Plattformzahlungen, Mehrfachmeeting-freie Account-Metriken und permanent die unbelegte Attribution/Profitabilität. Die Belegarten CLIENT_PAYMENT und PLATFORM_PAYMENT werden nicht miteinander vermischt. Keine wirtschaftliche Erfolgsaussage aus nominellen Konditionen, Termin-Entwürfen oder KI-Ausgaben.

**Vor produktiver Monetarisierungsbehauptung fehlen:** autorisierter Live-Bank-/Accounting-Abgleich, sichere Prüfung von Verträgen/Terminteilnahme, Budget-/Leistungsgrenzen, revisionsfeste Zeitperioden und Korrektur-/Stornoevents, geprüfte Kosten-Vollständigkeit, Umsatz-Attribution, drei zahlende Kunden und tatsächlich positive Unit Economics.
