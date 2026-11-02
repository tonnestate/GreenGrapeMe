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
