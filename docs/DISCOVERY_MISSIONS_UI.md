# GreenGrapeMe: Discovery-Missionen aus der Produktoberfläche

**Stand 2026-11-02; Entwicklungsbranch `feat/p0-sales-organization`; lokale Produktvorschau, keine freigegebene SaaS-Installation.**

## Implementierter Prozess

Der Anwender erstellt in der GreenGrapeMe-Oberfläche einen Discovery-Auftrag mit Angebot, Zielkundenprofil, Vertriebsziel und Quellenkontext. Der Auftrag wird zuerst persistent im GreenGrapeMe-Sales-Store registriert und von einem getrennten Worker verarbeitet.

**existing:** Ein bestehender, autorisierter StarFruitMe-Job wird mit `get_discovery_status`, `find_companies` und `get_company` gelesen. Keine neue externe Recherche.

**new:** Ein bounded Auftrag mit NACE-Klasse, WGS84-Region, optionalen Suchbegriffen und maximal 10 Suchabfragen kann über die tatsächlichen StarFruitMe-MCP-v2-Tools `create_discovery_job` und `run_discovery_job` laufen, **nur nach externer Quellenfreigabe durch den Host und bestätigter Nutzungsrechtsprüfung**. In der Standardkonfiguration blockiert.

Anschließend werden Quellenkandidaten in vorhandene GreenGrapeMe-Accounts importiert. Der SalesMission-Status und die Aufgaben stehen in derselben Benutzeroberfläche bereit. **Ohne tatsächliche autorisierte MangoMe-Aufnahme bleibt der Status `AWAITING_CANONICAL_WORK`.** Bei vertrauenswürdiger Host-Aufnahme können die vorhandenen PlumMe-Neurons Head of Sales, Market Intelligence und SDR quellengebundene, unverifizierte Empfehlungen erstellen. Es erfolgt **keine automatische Kundenansprache**.

Keine zusätzliche Firma-Master-Datenbank, kein eigener Google-Scraper, kein zweiter KI-Modellrouter oder allgemeiner Agenten-Orchestrator.

## Technische Grenzen

- Lokale API: `POST /api/discovery-jobs`, `GET /api/discovery-jobs`, `GET /api/discovery-job?id=…`. POST erfordert starken Viewer-Token, gleiche Origin, JSON-Schema und Body-Limit. Tenant stammt ausschließlich aus dem Host; Browser-Tenant wird ignoriert.
- Der Webserver ruft **nie** selbst eine externe Quelle auf. Der separate Worker betreibt die Bearbeitung, und die HTTP-Anlage vergibt keine Modell-, Kanal- oder Dispatch-Autorität.
- Ein Quell-Create-/Run-Aufruf schreibt **vor dem externen Effekt** ein persistiertes `CREATE_IN_FLIGHT`/`RUN_IN_FLIGHT`. Bei Antwortverlust wird `ADMISSION_UNCERTAIN` gemeldet, niemals automatisch blind erneut gesendet. MangoMe-Aufnahme nutzt ihren eigenen bereits implementierten Aufnahme-Fence.
- Bei Quellenkonflikten stoppt die automatische Verarbeitung. Eine StarFruitMe-Staging-Beobachtung ist **keine verifizierte juristische Firmenidentität**; BlackberryMe muss den Rechtsträger erst unabhängig und belegbar zuordnen.
- Die Anwendung ist weiterhin auf 127.0.0.1 begrenzt. Ein lokaler Token ist kein verkaufsfähiger SaaS-Login und darf nicht zur externen Benutzer- oder Mandantenautorisierung aufgewertet werden.
- Der Product-Worker ist eine fachliche Sales-Queue, kein Ersatz für MangoMe/PeachMe/PlumMe/PomeloMe.

## Lokaler Ablauf

Für die Weboberfläche zunächst einen starken geheimen `GG_VIEWER_TOKEN` im Host setzen. Dann:

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant demo-org --db sales.sqlite serve --port 8765
```

Die Oberfläche unter `http://127.0.0.1:8765/` öffnen und im Tab **Discovery-Aufträge** einen neuen Auftrag anlegen.

In einer zweiten Host-Sitzung startet der Worker. Ohne `--once` prüft er fortlaufend neue Aufträge:

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant demo-org --db sales.sqlite discover-worker --once
```

Nur bei **extern geprüften Quellenrechten** darf der vertrauenswürdige Host `GG_ALLOW_EXTERNAL_DISCOVERY=1` und `STARFRUITME_RIGHTS_CONFIRMED=1` für den vorgesehenen Donor konfigurieren. Ein Häkchen in der Oberfläche ersetzt diese Prüfung nicht.

Die Verbindung zu echten MangoMe-Arbeitsidentitäten ist nur für vertrauenswürdige Hosts mit authentifiziertem Actor, passendem Workspace, tatsächlicher aktueller Benutzeranforderung und expliziter Host-Autorisierung erlaubt: `GG_HOST_ACTOR`, `GG_HOST_WORKSPACE`, `GG_HOST_CURRENT_USER_REQUEST`, `GG_HOST_AUTHORIZATION_GRANTED=1`. Die PlumMe-Kostengrenze ist über `GG_NEURON_COST_USD` gesetzt. Keine dieser Angaben darf ein Modell selbst erfinden oder als automatisch erteilt gelten.

## Abnahme und weiterer Ausbau

Die neue Offline-Suite `tests/test_discovery_jobs.py` prüft mit eindeutig simulierten StarFruitMe-, PlumMe- und MangoMe-Antworten Quellen-, Rechte-, Mandanten-, Idempotenz-, Crash-Replay- und HTTP-Origin-Grenzen. GitHub-CI prüft Syntax und Unit-/Vertragstests. **Ein echter Host-End-to-End-Lauf wurde hier nicht durchgeführt.**

Verbleibende Produkt-Gates: BlackBerryMe-Identitätsnachweis als zwingender Zwischenauftrag; Quelljobs für gespeicherte Suchen, Zeitpläne und Freshness-Monitore; unabhängige MangoMe-Reconciliation nach unklaren Effekten; SaaS-Login/RBAC, echte Kundenrechte, Discovery-Geo-UI, rechtskonforme Kampagnen-/Setter-/Closer-Effects, Funnel-Builder und verifizierte Umsätze. Cloudflare-Code-Mode bleibt ein Benchmark-Kandidat und ersetzt nicht FruitStack.

Die Releaseplanung unter `docs/GESAMTKONZEPT_UND_RELEASEPLAN.md` bleibt verbindlich; diese Implementierung ist ein weiterer Release-0.3/0.4-Slice, **keine abgeschlossene Produktversion 1.0**.


## Zusätzliche Sicherheitsgrenze: Tenant-gebundene Quelljob-Freigabe

Auch ein **vorhandener** StarFruitMe-Job darf nicht allein durch Kenntnis seiner 24-stelligen ID gelesen werden. Der vom Benutzer erzeugte Discovery-Request wird nur verarbeitet, wenn sein Job in der hostseitigen Allowlist `GG_ALLOWED_EXISTING_STARFRUIT_JOBS` steht. Die Liste ist eine durch Komma getrennte Menge tatsächlich autorisierter IDs für **diesen einen Worker-/Tenant-Prozess**, z.B. `GG_ALLOWED_EXISTING_STARFRUIT_JOBS=0123456789abcdef01234567`. Ohne diese hostseitige Freigabe folgt `BLOCKED_SOURCE_POLICY / EXISTING_SOURCE_JOB_NOT_AUTHORIZED` **vor jeder Quelloperation**. Der Browser kann diese Liste nicht ändern.

Ein öffentliches Mehrmandanten-SaaS muss statt dieser lokalen Prozess-Allowlist einen serverseitigen, vom Source-Eigentümer überprüften Actor-/Tenant-/Job-Grant benutzen. Die freigegebene Job-ID allein ist kein verteidigungsfähiges SaaS-Berechtigungskonzept.


## 02.11.2026 – Verbesserte Mission-Isolation und verpflichtende BlackberryMe-Recherche

**Unveränderliche Quellkohorte:** Jeder GreenGrapeMe-SalesMission wird beim Erzeugen die eindeutige Menge ihrer höchstens 25 konkreten Opportunity-IDs zugewiesen. Zu jeder gehört ein SHA-256-Fingerprint der ursprünglichen Quellbelege. PlumMe sieht **nur diese Mission-Kohorte**, auch wenn andere Discovery-Jobs dasselbe Angebot bearbeiten. Änderungen am Quellbeleg, Löschen oder Suppression unterbrechen weitere Neuron-Stages mit `BLOCKED_SOURCE_REVISION`. Höhere Kandidatenzahlen werden transparent als `BLOCKED_ACCOUNT_CAPACITY` ausgewiesen, nicht stillschweigend abgeschnitten und als vollständig gemeldet; Batch-Splitting ist eine offene Produktweiterentwicklung.

**BlackberryMe-Integration:** Nach erfolgreicher StarFruitMe-Übernahme geht ein Product-Job in `AWAITING_BLACKBERRY` statt direkt zur kanonischen MangoMe-Aufnahme. Ein **separat konfigurierter Host-Worker** kann mit `GG_ENABLE_BLACKBERRY_RESEARCH=1` je Aufruf ein einziges Konto quellengebunden durch das tatsächliche BlackberryMe-MCP-Tool `blackberry_plan_company` untersuchen. Der bereits bestehende `research_account`-Vertrag speichert eine tenantbezogene, idempotente Recherchekarte. Die Product-Queue prüft, ob diese Karte tatsächlich persistent vorliegt und niemals behauptet, dies sei ein bestätigter Rechtsträger oder ein Kontaktmandat. Es werden **keine** LinkedIn-/Website-/E-Mail-Such- oder Kontakttools aufgrund eines bloßen Discovery-Listings ausgeführt.

Vor dem BlackberryMe-Toolaufruf steht ein persistenter `BLACKBERRY_IN_FLIGHT`-Fence. Geht die Antwort verloren oder widerspricht sie dem belegten Account, bleibt `BLACKBERRY_UNCERTAIN` für explizite unabhängige Reconciliation. Nur eine vollständig recherchierte Kohorte erreicht `AWAITING_CANONICAL_WORK`; erst danach darf ein authentifizierter FruitStack-Host MangoMe/PlumMe verwenden. Fehlt der BlackberryMe-Host, bleibt der Auftrag wartend, statt eine leere Verifikation zu simulieren.

**Testgrenzen:** `tests/test_mission_cohorts.py` und zusätzliche Fälle in `test_discovery_jobs.py` prüfen getrennte Accounts bei identischem Angebot, falsch zugeordnete Mandanten, nachträgliche Suppression/Quelländerung, fehlende BlackberryMe-Recherche, verloren gegangene Antworten und keine automatische Wiederholung. Offline-Tests sind weiterhin kein Beweis für konfigurierten Live-Provider-/Rechtsdatenzugriff.

**Noch offen:** unabhängige Unternehmens-Rechtsträgerverifikation und eindeutiges StarFruitMe↔BlackberryMe Matching (ein Firmenrechercheplan allein kann dies nicht leisten), Account-Batch-Splitting und Nachladen über die ersten 25 Kandidaten hinaus, tatsächliche Host-Smokes und die produktive autorisierte Kommunikations-/Setter-/Closer-Strecke.


## Batch-Verarbeitung und UI-Anzeige (02.11.2026)

Der Discovery-Worker unterstützt nun bis zu 100 zurückgegebene Kandidaten pro Aufruf. Bei 1–25 bleibt die bisherige einzelne, quellengebundene SalesMission erhalten; bei 26–100 werden deterministisch (nach Opportunity-ID sortiert) mehrere SalesMissions mit maximal 25 Accounts angelegt und in `sales_discovery_batches` gespeichert. Bei 60 Accounts entstehen die Gruppen 25+25+10. Die Gruppen besitzen eigenständige MangoMe-Work- und PlumMe-Ausführungsbelege, werden aber weiterhin vom *gleichen* GreenGrapeMe-Product-Worker verwaltet, ohne neue allgemeine Orchestrierung.

Neue Aggregatzustände: `BATCH_AWAITING_BLACKBERRY`, `BATCH_AWAITING_CANONICAL_WORK`, `BATCH_ADMITTED`. Jede Gruppe muss ihre BlackberryMe-Recherche abgeschlossen haben, bevor die kanonische MangoMe-Aufnahme erfolgt. Alle Gruppen müssen nach echten Neuron-Resultaten den Status `REVIEW_READY` erreichen, bevor der Gesamtauftrag `REVIEW_READY` meldet. Bei unterbrochenen Abläufen werden persistierte Kohorten und externe Admission-Fences wiederverwendet; source hashes, spätere Opt-outs und fremde Tenant-Daten werden vor jeder weiteren Aktion geprüft.

Die Weboberfläche zeigt Batch-Gesamtzahl, bereits abgeschlossene Gruppen und erfasste Accounts. **Keine Erfolgskennzahl behauptet reale Kundenkontakte.** Die implementierte Grenze von 100 Quellenkonten pro erster Abfrage stellt keine vollständige Pagination über einen gesamten StarFruitMe-Discovery-Job sicher; dies ist ein offenes Release-Gate. Tests im `tests/test_discovery_batches.py` verwenden eindeutige, offline simulierte Source-/BlackberryMe-/MangoMe-/PlumMe-Adapter – nicht den tatsächlichen Produktiv-Host.
