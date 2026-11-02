# GreenGrapeMe – Gesamtkonzept, FruitStack-Integration und Release-Roadmap

**Stand:** 02.11.2026 · **Fassung:** 1.0 / Research-Baseline · **Status:** Zielbild und spezifizierte Release-Arbeiten; keine Behauptung eines produktiven autonomen Vertriebsteams  
**Repository:** https://github.com/tonnestate/GreenGrapeMe  
**Entwicklungsbasis:** `feat/p0-sales-organization`, PR #1; beim Konzeptabgleich HEAD `9aa6ca71b54ec7a7041562553ef347f8e9b67565`.  
**Produktdefinition:** GreenGrapeMe ist eine eigenständige, kommerziell nutzbare B2B-Vertriebssoftware **und** eine native Geschäftseinheit im FruitStack. Produkt und Integration sind gleichrangige Voraussetzungen. Die operative Vertriebsautonomie ist das primäre Leistungsversprechen; SEO/GEO nur ein ergänzender Kanal.

> **Verbindliche Leitentscheidung:** Nicht ein einzelner Lead-Scraper, ein Funnel-Editor oder ein KI-Chatbot, sondern ein zusammenhängendes, möglichst autonomes *virtuelles Sales-Team*, das vom Zielmarkt über Discovery, Ansprache, Qualifizierung und Abschlussvorbereitung bis zum realen Kundenumsatz arbeitet. Bereits bestehende FruitStack-Fähigkeiten werden genutzt, nicht parallel nachgebaut. Kunden benötigen kein TonnEstate und keine Installation des FruitStack, um GreenGrapeMe als SaaS zu verwenden.

## 1. Ausgangspunkt und Abgrenzung

### 1.1 Die drei funktionalen Vorbilder

1. **Agentur Consulting Sales-Team** (https://agentur-consulting.de/salesteam): Vertriebsorganisation, Outreach, KI-Setter, Termine, Follow-ups, Closing sowie Vertriebsführung. Das Produkt dient als **funktionsbezogene Referenz**, nicht als Quelle übernehmbaren proprietären Codes oder unverifizierter Leistungszahlen.
2. **Perspective.co** (https://www.perspective.co/): KI-erstellte, interaktive Lead-Funnels, Qualifizierung, Conversion, personalisierte Ergebnisse, Terminübergabe und Optimierung. Insbesondere die 2026 dokumentierten KI-/MCP-Funnel-Funktionen sind ein Produktbenchmark.
3. **BabyLoveGrowth.ai** (https://www.babylovegrowth.ai/): unterstützende organische Nachfrageerzeugung durch Content und SEO/GEO. Dieser Bereich ist nachrangig; vorhandenes DragonFruitMe-Webwissen zuerst wiederverwenden.

**Abgrenzung:** Kein TonnEstate-Nachbau, keine zweite Golden-Company-Datenbank, kein neuer allgemeiner LLM-Router, kein zweiter FruitStack-Memory-/Governance-Stack, keine ungeprüfte Massenansprache und kein SEO-first-Produkt. Bezahlte Datenprovider und Cloud-Dienste sind optional, nicht stillschweigende Voraussetzungen.

### 1.2 Zielkunde und Produktversprechen

Anwendungsfall: B2B-Unternehmen, Agenturen und Dienstleister, die ein eigenes Vertriebsteam teilweise oder weitgehend automatisieren wollen. Ein Kunde hinterlegt sein Angebot, ICP, geographischen Markt, Preis-/Vertragsgrenzen, Kommunikationsrechte und Budget. GreenGrapeMe sucht überprüfbare Chancen, löst Firmen- und Entscheideridentitäten auf, bewertet Signale, plant vertriebliche Maßnahmen, führt zulässige Aktionen aus, qualifiziert Antworten, organisiert Termine und zeigt den tatsächlichen wirtschaftlichen Erfolg.

**Nicht als Erfolg zählen:** Datensätze, Nachrichtenentwürfe, versuchte Sendungen, fiktive Termine, ungeprüfte „Win-Wahrscheinlichkeiten“ und KI-Selbstbewertungen. Erfolg entsteht erst durch verifizierte Pipeline- und Umsatzereignisse.

### 1.3 Zwei Betriebsprofile – ein Produktkern

- **FruitStack-native:** GreenGrapeMe steuert seine Sales-Missionen über bereits vorhandene FruitStack-Rollen-/Work-/Effect-Capabilities. Bestehende StarFruitMe-, BlackberryMe- und KIGOR-Quellen liefern fachlich typisierte Beobachtungen. Die vorhandene FruitStack-Supply, der Harness und die Ausführungs-/Assurance-Mechanismen werden *nach tatsächlicher API-Prüfung* eingebunden.
- **Managed SaaS:** Derselbe GreenGrapeMe-Fachkern und dieselben Sales-Agenten laufen als verwalteter Dienst für getrennte Kundenorganisationen; der Anbieter betreibt die internen FruitStack-Komponenten. Nutzer brauchen die technischen Komponenten nicht selbst. Kunden-CRM, E-Mail, Telefonie, Kalender oder Billing werden über austauschbare Ports angeschlossen.
- **Wichtige Reihenfolge:** **Fachverträge und interne Integration jetzt**; umfangreiche *externe kundenspezifische Adapter* später. Ein expliziter Port ist nicht automatisch eine bereits funktionierende Schnittstelle.

## 2. Fachlicher End-to-End-Prozess

```text
OFFER/ICP/BUDGET
      ↓
MARKT- UND ACCOUNT-DISCOVERY (Branchen, Geografie, Standorte)
      ↓
RECHTSTRÄGER- UND ENTSCHEIDERKLÄRUNG (Quellen, Revisionen, Unsicherheit)
      ↓
KAUFSIGNALE / RELEVANZ / WIRTSCHAFTLICHE QUALIFIKATION
      ↓
HEAD OF SALES: Priorisieren, Kampagnen wählen, Budget verteilen
      ↓
PERSONALISIERTE LEISTUNGSANALYSE / KAMPAGNE / FUNNEL
      ↓
ZULÄSSIGE KONTAKTAKTION ODER INBOUND-LEAD
      ↓
KI-SETTER: Antworten, Bedarf, Termin, Nurturing / Reaktivierung
      ↓
ACCOUNT EXECUTIVE: Angebot, Einwände, Freigabe, Vertragsabschluss
      ↓
CUSTOMER SUCCESS: Onboarding, Bestand, Expansion
      ↓
REVOPS: Bezahlter Umsatz, Marge, CAC, Lernen → Head of Sales
```

Jeder Übergang ist ein eigenständiger, nachvollziehbarer Zustandswechsel mit `tenant_id`, `opportunity_id`, `work_id`, Rolle, Quellenreferenzen, Zeitpunkt, Ergebnis, Kosten, konkreter Autorität und ggf. externem Effektbeleg. Unbekannt bedeutet **UNKNOWN**, nicht „erledigt“ oder „nicht vorhanden“.

### 2.1 Discovery als vollwertiger Produktbereich

GreenGrapeMe muss *selbst* ein nutzbares Discovery-Modul anbieten:

- Suchaufträge nach Branche/NACE, Region, Radius, Größe/Merkmalen und Zielkundenprofil; wiederholbare gespeicherte Suchen.
- Firmen- und Standortkandidaten mit Karte/Liste, Quellenbelegen, Qualität, Beobachtungsdatum, Dublettenhinweisen, Filter und Änderungen im Zeitverlauf.
- Trennung von **Standortkandidat**, **rechtlicher Firma**, **Person** und **Vertriebs-Account**. Ein Kartenlisting ist keine verifizierte juristische Person.
- Website-/Karriere-/News-/Ausschreibungs-/Technologie-Signale; stale/fehlende Quellen sichtbar, nicht als Negativbefund ausgeben.
- Quellenrechte und Nutzungsbedingungen pro Collector prüfen. StarFruitMe-Google-Maps-Discovery ist ein Kandidat, kein garantierter lizenzfreier Komplettdatensatz.
- Manuelle Identitäts- und Dublettenprüfung, wenn deterministische Zuordnung nicht möglich ist.
- Ein nachvollziehbarer Übergang **Gefunden → Geprüft → Qualifiziert → Sales-Account → Vertriebsauftrag**.
- Wiederholbare Discovery-Monitore mit Grenzen für Scope, Rate, Ausgaben und Abrufhäufigkeit.

### 2.2 Vertrieb, Kommunikation und Conversion

- ICP-/Offer-Management mit Nutzenhypothesen, verbindlichem Angebotskatalog, erlaubten Preisbändern und Zielmargen.
- Konto-/Personenrecherche, signalgebundene Sales-Briefs und individuelle wertstiftende Analysen als Ansprachegrundlage.
- Kampagnen mit Experimenten, Sequenzen, Stop-Bedingungen, Kanalpräferenzen, Kapazitätsgrenzen und qualifizierten Freigaben.
- Zentraler Konversations-/Inbox-Zustand: Antwortklassifikation, Absicht, Einwand, Rückfrage, Terminwunsch, Bounce, Abmeldung, menschliche Übernahme.
- Perspective-artiger visueller Funnel einschließlich bedingter Fragen, Einwilligung, Ergebnis, Conversionereignis, Terminhandoff und A/B-Auswertung.
- Setter mit Gesprächskontext, quellenbelegten Produktaussagen, echtem Kalenderstatus, Bestätigung und No-Show-Prozess.
- Closer mit Opportunity-Dossier, bestätigten Preisen/Leistungen, Angebotsversionen, Verhandlungskompetenzgrenzen, Dokumenten-/Vertragsfreigabe und Ergebnisbelegen.
- Customer Success und RevOps mit dokumentierten Upsell-/Renewal-Signalen und klarer Umsatzreconciliation.

## 3. Die virtuellen Vertriebsmitarbeiter

Eine **Sales-Rolle** ist eine delegierbare *geschäftliche Funktion*, nicht notwendig ein permanent laufender LLM-Prozess. Rollen können durch einen FruitStack-Neuron-Work-Auftrag realisiert werden, sobald die aktuelle Kompatibilität nachgewiesen ist.

| Rolle | Primärer Auftrag | Zulässige autonome Wirkung / Beleg |
| --- | --- | --- |
| **Head of Sales / CRO** | ICP, Angebot, Prioritäten, Budget, Kampagnenportfolios | Interne Entscheidungen und neue Arbeitsaufträge, versionierte Hypothesen; keine eigenmächtige Preis-/Risikogrundsatzänderung |
| **Market Intelligence** | Markt, Firmen, Standorte, Signale, Ausschreibungen | Recherchieren, quellenbelegt beobachten, Unsicherheiten markieren |
| **SDR / Prospecting** | Account-Fit, Entscheider-/Kontaktrelevanz, Priorisierung | Dossiers, Qualifikationsstatus, Freigabevorlagen |
| **Campaign / Personalization** | Nutzenargumentation, Sequenzen, Varianten, persönliche Analysen | Entwürfe und getestete interne Varianten; externer Versand nur durch erlaubten Effekt |
| **Funnel / Growth** | Lead-Funnels, Formulare, Conversion, Onsite-Experimente | Staging, freigabefähige Publikationsänderungen, Metriken |
| **AI Setter** | Eingangsdialog, Bedarf, Folgefragen, Terminvereinbarung | Automatisches Handling nur in autorisierten Kanälen; echte Buchung nach Freigabe/realem Kalenderstatus |
| **AI Account Executive / Closer** | Lösung, ROI, Einwände, Angebote, Deal-Fortschritt | Verifizierte Angebote innerhalb delegierter Grenzen; bindende Abschlüsse nur bei expliziter rechtlicher Autorität |
| **RevOps** | Funnel, Umsatz, Ausgaben, Attribution, Qualitätsvergleich | Report, Anomalien, Budgetempfehlungen, kontrollierte Optimierung |
| **Customer Success** | Onboarding, Kundenstatus, Verlängerung, Expansion | Aufgaben und erlaubte Betreuung; keine erfundenen Vertrags-/Zahlungsereignisse |

Zusammenarbeit erfolgt über eine **Sales-Mission** mit Ziel, Auftraggeber/Organisation, Kontextverweisen, Rollen-/Kostenbudget, nächsten fachlichen Aktionen und terminalem wirtschaftlichem Ergebnis. Eine Rolle darf keine fremde Autorität erteilen; das Host-/Effect-Gate entscheidet unmittelbar vor externer Wirkung.

## 4. FruitStack-Integration als Architekturpriorität

### 4.1 Vorhandene Fähigkeiten – keine neue Infrastruktur erfinden

| Vorhandener Baustein | GreenGrapeMe-Aufgabe | Verifizierungsgrenze |
| --- | --- | --- |
| **StarFruitMe** | Geografische Unternehmens-/Standort-Discovery und Provenienz | MCP v2, echtes `tonnestate-golden-company-discovery-handoff-v1`-JSONL; kein direkter Golden-Company-Write |
| **BlackberryMe** | Rechtsträger-/Entscheiderauflösung, Rollenfilter, belegte Kommunikationswege | Tatsächlich veröffentlichte MCP-Operationen prüfen; internes Kommunikations-Backend nicht mit produktiver Remote-Freigabe verwechseln |
| **KIGOR** | Datiertes, quellenbelegtes Opportunity-/Vergabewissen, Revisions-/Wirtschaftlichkeitsmuster | Read-only-MCP; öffentliches Vergabeverfahren ist keine allgemeine Kaufabsicht und keine automatische BID-Entscheidung |
| **DragonFruitMe** | Website-Strukturen, Fakten, Onpage-Signale | Datenlieferant, kein vollständiger SEO-Service; GPLv3-Rechte bei Code-Reuse prüfen |
| **PlumMe** | KI-Arbeitskräfte/Neuron-Leases, Kosten-/Supply-Policy | Echte Host-Version und Rolle/Authority/Budget-Kontrakte vor Aufruf verifizieren |
| **PeachMe** | Kognitive Sitzung/Context/Harness, Step- und Budgetgrenzen | Nicht alle dokumentierten Integrationen sind produktiv nachgewiesen |
| **CherryMe** | Recherche, kritische Überprüfung, Evidenz/Assurance | Private Crown-Jewel-Komponente; keine Veröffentlichung von Prompts/Code/Providerpfaden |
| **MangoMe** | Langlebige WorkIdentity, Arbeitszustände, Evidence, externe Ergebnisse | Kein zweiter kanonischer Work-Store innerhalb GreenGrapeMe |
| **PomeloMe** | Freigabe, begrenzte Effekte, sicherer Replay-/Recovery-Pfad | Runtime-Reife/DBOS-Vertrag prüfen; kein ungeprüfter Ersatz für Outbox/Host |
| **TonnEstate** | Erster möglicher interner Kunde/CRM-Adapter | Kein hartes Datenbank- oder Deployment-Coupling; insbesondere nicht die einzig mögliche CRM-Quelle |

**Zuständigkeit:** GreenGrapeMe hält *Sales-Produktzustand* (Mandanten, Angebote, Sales-Accounts als Referenzen, Kampagnen, Conversations/Deals, Preise, KPI-Fakten). FruitStack hält *KI-Arbeits-/Assurance-/Execution-Wahrheit* in den jeweils zuständigen Komponenten. StarFruitMe hält Discovery-Staging; die kanonische juristische Firmenidentität bleibt bei der für den betreffenden Betrieb autorisierten Quelle.

### 4.2 Stabile fachliche Ports, externe Anbieter später

Die erste Implementierung muss **innere Domänenkontrakte** festlegen und nutzen:

```text
DiscoveryProvider       -> AccountObservation[], evidence + freshness
IdentityProvider        -> IdentityResolution / NOT_VERIFIED / CONFLICT
SignalsProvider         -> BuyingSignal[] + source + observed_at
AgentWorkProvider       -> admitted role task + evidence/receipt
CommunicationProvider   -> channel capability + policy + delivery result
ConversationProvider    -> threaded inbound/outbound events
FunnelProvider          -> funnel + versions + conversions
CalendarProvider        -> real availability + booking receipt
ProposalProvider        -> approved quote + contract evidence
RevenueProvider         -> independently verified invoices/payments
```

Ein Port stellt niemals eine stillschweigende Liveintegration dar. Erste Adapter dürfen *in-process* oder über bestehende, bereits geprüfte lokale MCP-/JSONL-Schnittstellen laufen. Spätere öffentliche REST-/Webhook-/CRM-/Kalender-Connectoren werden auf denselben stabilen fachlichen Vertrag abgebildet. Adapterfehler blockieren nur ihre betroffene Fähigkeit, nicht die gesamte Vertriebsmannschaft.

**SaaS-Abgrenzung:** Eine Mandantenorganisation darf nicht dieselbe SQLite-Datei und dasselbe lokale Hostvertrauen als einziges Sicherheitsversprechen verwenden. Vor öffentlichem Verkauf sind Authentifizierung, Organisation/Rollen, serverseitige Autorisierung, Mandantentrennung, Backups, Migrationen, Datenschutz, Geheimnisverwaltung, Rate-/Budgetlimits und klare Betriebsverantwortung erforderlich.

### 4.3 Cloudflare Code Mode – gezielter Donor, nicht der neue FruitStack-Kern

Forschungsquellen: https://blog.cloudflare.com/code-mode-mcp/ (20.02.2026), https://developers.cloudflare.com/agents/model-context-protocol/guides/build-codemode-mcp-server/ (27.10.2026), https://github.com/cloudflare/agents und https://developers.cloudflare.com/agents/concepts/agentic-patterns/long-running-agents/ (Oktober 2026).

**Prüfhypothese:** StarFruitMe-Recherche, BlackberryMe-Bewertung und Quellenfilter können durch kompakt ausgeführte, typisierte Tool-Sequenzen *weniger Modellrunden und weniger Eingabetokens* benötigen. Cloudflares rund 1.000-Tokens-Argument betrifft einen speziellen API-/Schemasvergleich, keine bereits gemessene GreenGrapeMe-Ersparnis.

- **Research-Donor:** `@cloudflare/codemode` (MIT, experimentell); `cloudflare/agents`-Quellstand am 02.11.2026: `be1749221ab3efc8be4e976d8e7d8344d1446032`.
- **Vergleichsarme:** A = gewöhnliche MCP-Ausführung; B = begrenzte Code-Mode-Ausführung derselben zugelassenen read-only Capabilities.
- **Gleich halten:** Datenquelle/Golden Set, Modell, Berechtigung, Fehlerfälle, Tokenbudget, Hosthardware/Netzwerk, Toolresultate und Kostenmessung.
- **KPIs:** Kosten pro *korrekt qualifizierter* Opportunity, Token/Task, Modell-Roundtrips, P50/P95-Latenz, Recall/Precision der richtigen Firmen/Entscheider, unbeabsichtigte Effekte, Recovery und Tool-Ausfallrate.
- **Grenze:** Kein `eval` im Host, keine unkontrollierte Netzfreigabe, kein Einblick in Credentials, keine Ausführung privilegierter Writes direkt aus generiertem Code. Runtime-/Approval-Fähigkeiten sind versioniert; Cloudflare unterscheidet Legacy-`createCodeTool` von neueren Runtime-Connector-Approvals. Nur nach Proof und Effect-Gate-Tests produktiv einschalten.
- **Kein Cloudflare-Lock-in:** Der GreenGrapeMe-Fachvertrag darf weder Worker-spezifische Datenmodelle noch zwingende Cloudflare-Betriebskosten erhalten. Lokale FruitStack-Ausführung bleibt Baseline.

## 5. Aktueller, nachgewiesener Projektstand

**Geprüft:** GitHub `feat/p0-sales-organization`, HEAD `9aa6ca71b54ec7a7041562553ef347f8e9b67565`, offener PR #1, keine Freigabe/Merge in `main`.

| Vorhanden im Branch | Genaue Reichweite |
| --- | --- |
| `src/greengrapeme/sales.py` | Deterministische Erstentscheidung: Evidenz, Konflikte, Suppression, nur Draft/Freigabe |
| `src/greengrapeme/sources.py` | **Dateiimport** realer StarFruitMe-Handoff- und KIGOR-MCP-Ausgabeformate; kein live aufrufender MCP-Client |
| `src/greengrapeme/intelligence.py` | OpenOutbound-inspirierte halbwertszeitgewichtete Signalwertung und vorsichtige Reply-Prechecks |
| `src/greengrapeme/operations.py` | SQLite-basierte, mandantenbezogene Sales-Work-Items, Replay-/Duplikatprüfung, Rankings, Inbox-Status, Sperren |
| `src/greengrapeme/cli.py` | Einmalige `autopilot`-Import-/Triagestrecke, `cycle`, `queue`, `rankings`, `overview`, `reply` |
| `tests/test_sales.py` / `tests/test_integration.py` | Offline-Fixtures und deterministische Invarianten; keine echte Umsatz- oder Live-Sales-Abnahme |

**Nicht vorhanden:** fortlaufender unabhängiger Discovery-Dienst, echter BlackberryMe-Entscheiderkontakt und Rechteprüfung, FruitStack-Neuron-Ausführung, dynamische Sales-Planung, Sender-/Mailbox-Effektbelege, echte produktive Inbox, Funnel-Oberfläche, Terminbuchung, Preis-/Vertrags-Engine, Zahlungsverifikation, öffentliches SaaS.

**Vor jedem Liveversand konkret zu reparieren:** Suppression derzeit Opportunity-orientiert; es fehlen übergreifende *Empfänger-/Firmen-/Mandanten-/Kanal*-Sperrprüfung und ein belegter Consent-Vertrag. Das freie `verified_company`-Boolean darf nicht als verifizierte Identität akzeptiert werden; nur autorisierter Resolver/Beleg kann das setzen. Quellenaustauschkonflikte benötigen explizite Reconciliation, nicht dauernde Blockaden oder stilles Überschreiben. Einmalige `autopilot`-CLI ist noch kein verlässlich geplanter Agentenbetrieb. Die Reply-Klassifikation ist bewusst nur eine Vorprüfung, keine vollständige rechtliche Auswertung oder semantische Setter-KI.

## 6. Weitere Donor-Research: konkrete Implementierungsvorteile

Research-Kennzeichnung: **ADAPTED** = bereits eigenständig implementierter Mechanismus; **REVIEWED** = Code/Dokumentation gelesen, noch nicht übernommen; **CANDIDATE** = weitere Code-/Lizenz-/Betriebsprüfung; **REFERENCE** = Funktionsbenchmark, kein Code-Reuse.

| Donor und verifizierter Stand | Substanz / konkrete Entnahme | Status und Grenze |
| --- | --- | --- |
| **OpenOutbound** https://github.com/xyluxx/openoutbound, `bc158cac6548ab54699442d159cc2130570b9a78`, Apache-2.0 | Signals, zeitabhängige Score-Logik, konservative Inbox-Klassifikation; danach Campaign-FSM, Approval-/Budget-Gate, idempotente Effects, Report/Reply-Operations | **ADAPTED** nur erster Teil; weitere Bausteine gezielt isoliert übernehmen. Kein komplettes Fremdbackend |
| **AgentSDR** https://github.com/Kandid-ai/AgentSDR, `138a56a70cb361cc39d95ef1def2f2ca097a672a`, MIT | Multi-Tenant-Webprodukt, zentrale Inbox, Kanalzustände, Lead-UI, Sendezeiten, Org-Isolationstests und Credential-Grenzen | **REVIEWED**, Vergleich zu eigener SaaS-Oberfläche; Unipile/Workspace/OpenRouter kosten- und bedingungsabhängig |
| **KIGOR** https://github.com/tonnestate/KIGOR (privat) | Source-Monitoring, Revision/Dedupe, Evidence/UNKNOWN, wirtschaftliche Opportunity-Prüfung, Projektakte | **ADAPTED** bisher nur Exportformat; keine freigegebene interne Codekopie oder produktive Live-Lesung |
| **StarFruitMe / BlackberryMe** (privat) | Firmen-/Standort-Discovery, Rollen-/Identitätsklärung, Kontakt-/Kanal-Policy | **ADAPTED** nur StarFruit-Handoff und dokumentierte Konzepte; Liveintegration noch offen |
| **Autonnel** https://github.com/autonnel/autonnel, `55f6831047bc9ef2b53076a5d43d266afad6682e`, Apache-2.0 | KI-generierte, editierbare Funnel-Strukturen, Landingpages, A/B, Conversion/Checkout, MCP, Self-host | **NEUER REVIEWED DONOR** für Perspective-ähnlichen Funnel; nicht gesamte Shop-/PostgreSQL-Plattform duplizieren |
| **Nuraveda AI Sales Agent** https://github.com/Nuraveda/ai-sales-agent, `cd0efc9aa25a0a94130e9f2779d7ee4688ac1c00`, MIT | Discovery → Enrichment → wertbezogener Draft → HITL-Freigabe → Feedback/Unsubscribe | **NEUER REVIEWED DONOR** für zusammenhängende Sales-Aufgaben; nicht dessen Google-/Discord-/Resend-Provider als Pflicht |
| **GTM Superintelligence** https://github.com/attentiontech/gtm-superintelligence, `15d60c01293721c39e0b8937fe9cbf09fcb21cc4`, Apache-2.0 | Transkriptadapter, Deal-/Account-Health, YAML-Rubriken, 30 Post-Call-Agentenmuster, belegtes Coaching | **REVIEWED**; Rohtranskripte, echte Lizenzen und Zustimmung erforderlich; keine erfundenen Win-Scores |
| **Cloudflare Agents / Code Mode** https://github.com/cloudflare/agents, `be1749221ab3efc8be4e976d8e7d8344d1446032`, MIT | Kombinierte Tools, typisierte Code-Ausführung, Durable-Agent-Patterns, Skills/Handoffs | **EXPERIMENTELLER DONOR** für B-Test, keine unkontrollierte Codeausführung und keine Ablösung von MangoMe/PomeloMe |
| **SurveyJS** https://github.com/surveyjs/survey-library, MIT für Form Library | Bedingte Qualifikationsfragen und Form-Rendering | **CANDIDATE**; kommerzieller Survey Creator gesondert lizenzieren |
| **LiveKit Agents** https://github.com/livekit/agents, Apache-2.0 | Echtzeit-Voice-/SIP-Agenten, Gesprächsübergaben | **CANDIDATE** für erlaubte Telefonate; Telco/TTS/STT separat kostenpflichtig oder selbst gehostet |
| **Vexa** https://github.com/Vexa-ai/vexa | Sprecherbezogene Live-Meeting-Transkripte als Quelle für Post-Call-Sales-Agenten | **CANDIDATE**, konkrete Lizenz/Einwilligung/Produktivbetrieb vor Übernahme erneut prüfen |
| **Documenso / Formbricks / Typebot** | Dokumente, Forms und Chat-Flows | **RECHTEPRÜFUNG**: AGPL/mischlizenzierte/Source-Available-Teile nicht ungeprüft in proprietäres SaaS kopieren |
| **Perspective / BabyLoveGrowth / Agentur Consulting** | Feature-/UX-/Geschäftsmodellreferenzen | **REFERENCE**; kein quelloffener Code-Donor |

**Wirtschaftliche Donor-Strategie:** Ein fehlendes, klar messbares fachliches Primitive adaptieren, nicht eine zweite Komplettanwendung installieren. Vor Copy: Dateipfad/SHA, Lizenz+NOTICE, Third-Party-Dependencies, benötigter SaaS-Service, Betriebskosten, Tests, Mehrwertgegenversuch und Integrationsvertrag dokumentieren.

## 7. Verbindlicher Releaseplan

Releases sind **Fertigstellungs-Gates**, keine Zeitversprechen. Kein Gate gilt allein wegen bestehender Tests, Readme-Behauptungen oder synthetischer Demos als produktiv abgenommen.

### Release 0.2.0 – Konsolidierung, harte Produktverträge, Sicherheitsreparaturen

**Implementieren**
- Bestehende `sales.py`/`operations.py`/`sources.py`-Verträge konsolidieren; `tenant_id`/`account_id`/`location_id`/`person_id`/`opportunity_id`/`work_id` strikt trennen.
- Ältere Quellenrevisionskonflikte deterministisch reconcilebar machen; unbekannte Identitäten nicht als „verified“ durch freien Parameter akzeptieren.
- Mandantenweite und empfängerweite DNC-/Consent-/Kommunikationspolicy modellieren, mit Änderungs- und Widerrufshistorie.
- Ein vertragsfähiges Sales-Mission-/Offer-/ICP-/Kampagnenmodell mit Status, Abbruch, Budget, Rollen und Provenienz schaffen.
- Transparente Command- und Event-Schemata samt Fehlertaxonomie; keine zusätzliche allgemeine FruitStack-Eventarchitektur.
- Test-Kit mit adversarialen Inputs, zeitabhängigen Signalen, Dubletten, Mandantentrennung, Opt-out, Crash-Recovery und Fehleroffenlegung.

**Done wenn** importierte Daten unter demselben Tenant identisch reproduziert werden; fremde Mandanten nichts lesen/ändern können; ein falscher `verified_company`-Flag keine Autorität verleiht; ein Opt-out alle betroffenen externen Aktionen unterbindet; vorhandene Originaltests unverändert grün bleiben.

**Donor**: OpenOutbound Approvals/Control/Replay, AgentSDR Tenant Tests. **Abhängigkeiten:** keine Live-Dienste.

### Release 0.3.0 – Native, dauerhafte FruitStack-Sales-Missionen

**Implementieren**
- Tatsächlich installierte Schnittstellen/Versionen von PlumMe, PeachMe, MangoMe, CherryMe und ggf. PomeloMe lesen und kompatiblen Host-Adapter bauen.
- Ein Auftrag `SalesMission(offer, ICP, geography, budget, criteria)` startet delegierbare Rollen: Head of Sales → Market Intelligence → SDR; semantische Rückgaben mit Evidence und Zeitstatus.
- Model-Limits, Role-Leases, kontinuierliche Missionszustände, Unterbrechung/Wiederaufnahme und budgetierte automatische Folgeaufträge; kein eigener zweiter autonomer Brain-/Memory-Loop.
- Agenten liefern realen Output oder `INCOMPLETE/UNKNOWN`; nicht „Provider gab Text zurück = Vertriebserfolg“.
- Autonomiegrade pro Handlung: interne Reads automatisch; interne Verbesserungsvorschläge automatisch; externe Writes nur nach gültigem Effect-Policy-Check.

**Done wenn** ein echter FruitStack-Modellaufruf für eine gemessene Sales-Mission erfolgt und eine zweite Session denselben dauerhaften Work-Status fortsetzt; Fault Injection/Timeout erzeugt keine doppelte Aktion; modellbedingte Kosten und Quellennachweise sind prüfbar.

**Donoren**: vorhandene FruitStack-Runtimes, selektive Muster aus Cloudflare Long-running Agents; nicht Cloudflare als Pflicht-Host.

### Release 0.4.0 – Discovery-Produkt und echte Data Intelligence

**Implementieren**
- Authorisierte echte StarFruitMe-MCP-Discovery-Jobs planen/ausführen/verfolgen; Quellstatus, Fehler und rechtliche Zugriffsfreigabe sichtbar.
- BlackberryMe-Entscheider-, Relevanz- und Legal-Identity-Vertrag mit echten Runtime-Routen prüfen und integrieren; KIGOR als getrennte, read-only Ausschreibungsquelle.
- Branchen-/Geo-Suche, Trefferliste/Karte, Quellendossier, Firmenseite, Standorte, Identitätskonflikte, Kauf-/Veränderungssignale, Watchlists, Alerts.
- Signal-Score zur *Priorisierung*, nicht als kalibrierte Kaufwahrscheinlichkeit; Source-Freshness, signal decay, rückwirkende Korrekturen.
- Discovery-Ergebnisse in Sales-Accounts überführen, ohne StarFruitMe-/TonnEstate-Stammdaten heimlich zu verändern.

**Done wenn** ein echter autorisierter Suchlauf im Host deterministisch zu sichtbaren, prüfbaren Accounts und passenden Sales-Work-Items führt; bekannte False Merges und leere/gesperrte Quellen korrekt erkannt werden. Für ein definiertes Testgebiet Precision, Abdeckung und Kosten separat messen.

**Donoren**: StarFruitMe, BlackberryMe, KIGOR, DragonFruitMe, OpenOutbound Signal-Monitors.

### Release 0.5.0 – SDR-Autopilot und Kampagnen-Engine

**Implementieren**
- Zielgruppe/ICP → gefilterter Account → belegbarer individueller Nutzenbrief → kampagnenfähiger Entwurf.
- Versionierte Kampagnen/Sequenzen mit Wartebedingungen, Abbruchbedingungen, Zeitzonen, Feedback, kontrolliertem Lernen und A/B-Kontrollarm.
- Kanalentscheidung aus tatsächlicher Präferenz/Beziehung/Rechtslage; aktionsgenaue Freigabe, Consent, Mailbox/LinkedIn-/Telefonrechte und DNC unmittelbar vor jeder Wirkung.
- Freigegebene externe Aktionen mit idempotenten Work-/Message-IDs, zustandsabhängigen Retries, Outbox, bestätigter Zustellung, Bounce/Opt-out, Kill-Switch und Provider-Ausfall.
- Ein gemeinsamer Agent-/Operator-Arbeitskorb für Freigaben, Korrekturen und unbekannte Versandergebnisse.

**Done wenn** ein erlaubter **Echtkanal-Pilot** von geprüfter Opportunity bis zum belegten erfolgreichen oder gescheiterten Effekt vollständig verläuft; ohne Freigabe/gesetzliche Grundlage keine Zustellung; Crash/Replays niemals blind doppelt versenden; Zustell-UNKNOWN bleibt offen.

**Donoren**: OpenOutbound Campaign FSM/Inbox/Approval/Effects, AgentSDR kanalübergreifende Queue, BlackberryMe Kommunikationsvertrag. Nicht zulässige „kalte“ Mail-/Massennachrichten bleiben gesperrt.

### Release 0.6.0 – Setter, Conversation Intelligence und Perspective-Funnels

**Implementieren**
- Inbound-Thread-, Gesprächs-/Kontakt- und Lead-State über alle unterstützten, autorisierten Kanäle; gesicherte Sprecher-/Thread-Zuordnung, semantische Antwortklassifikation, Termininteresse, Privacy und menschliche Übernahme.
- KI-Setter mit validiertem Wissenskatalog, Rückfragen, Lead-Fit, Notizen, Gesprächszusammenfassungen und Freigabebudget.
- Funnel-Designer mit Vorlagen, verzweigten Fragen, veröffentlichten Varianten, Formular-/Consent-Belegen, Lead-Zuordnung, Conversion-Ereignissen.
- Echte Terminangebote und Verfügbarkeitschecks; Buchung nur über tatsächlichen CalendarProvider und gültige Berechtigung; Held/No-show/Reschedule separat.
- Lücken zwischen anonymem Funnel-Lead und Unternehmen/Person nicht stillschweigend schließen.

**Done wenn** ein echter Inbound-Testlead einen Funnel durchläuft, qualifiziert wird und einen vom Kalender bestätigten Termin erzeugt, der korrekt der Opportunity zugeordnet ist. Opt-out, falsche Verfügbarkeit und unterbrochene Konversationen bestehen negative End-to-End-Tests.

**Donoren**: Autonnel (Funnel-Autorenschaft), SurveyJS (Formulare), AgentSDR (Inbox), OpenOutbound (Reply/Meetings). Keine zweite Komplett-CRM-App.

### Release 0.7.0 – Account Executive/Closer, Angebot und Vertragsstrecke

**Implementieren**
- Sales-Dossier aus geprüften Kundenbedürfnissen, Angebotskatalog, Vergleichen, Preisen, Konditionen, eindeutigen Einwänden und Gegenargumenten.
- Produkt-/ROI-Rechnung aus **kundenseitig bestätigten Annahmen**; UNKNOWN statt erfundener Einsparungen.
- Versionierte Angebotsentwürfe, Verhandlungsgrenzen, Rabatt-/Lieferfreigaben, Dokumentenstatus und Unterschrifts-/Vertragsergebnis nur aus unabhängiger Quelle.
- Sales-to-CS-Handoff und CRM-Export über Fachvertrag.

**Done wenn** ein vollständiger Testdeal von echter qualifizierter Opportunity über freigegebenes Angebot bis zu belegtem Vertragsereignis verfolgt wird; ohne Befugnis keine bindende Zusage/Signatur. Gegenprobe mit geänderten/fehlenden Preisen und widersprüchlichen Konditionen.

**Donoren**: GTM Superintelligence Deal-Rubriken; KIGOR Evidence/Cost-Regeln; Dokumenten-/E-Signatur-Provider nach Lizenz-/API-Prüfung.

### Release 0.8.0 – Head of Sales, RevOps und geschlossener wirtschaftlicher Regelkreis

**Implementieren**
- Umsatz- und Kostenereignisse aus überprüfbaren Quellen (Angebot, Vertrag, Rechnung, Zahlung, Storno, Erstattung).
- Funnel-Kennzahlen: qualifizierte Accounts, zulässig kontaktierte Leads, echte Replies, qualifizierte Termine, gehaltene Termine, Angebote, bezahlte Kunden.
- Attributionsregel versionieren; Kosten nach Datenbeschaffung, Modell, Kanal, Kampagne, Agent und Bearbeitung unterscheiden.
- Gewinn-/Verlustanalyse, A/B-Test und konservative datengetriebene Anpassung von Zielgruppe, Signal-Gewicht und Kampagnenpriorität.
- Head of Sales kann interne Budgetprioritäten innerhalb delegierter Grenzen automatisiert anpassen, aber keine höhere Ausgabenfreigabe selbst verleihen.

**Done wenn** reale gebuchte Zahlungen gegen Opportunity- und Kampagnenbelege abgeglichen sind; Testkonten/Fixtures/Schätzungen ausgeschlossen bleiben; ein nachweisbar schlechter Arm gestoppt werden kann und ein besserer nur auf Basis auswertbarer Daten bevorzugt wird.

**Donoren**: OpenOutbound Reporting, GTM Superintelligence Post-Call-/Deal-Health, FruitStack bestehende Evaluationsmechanismen.

### Release 0.9.0 – KI-Telefonie, Customer Success und Code-Mode-Proof

**Implementieren**
- Erlaubte Sprachkommunikation mit transparentem KI-Status, dokumentierten Telefonie- und Aufzeichnungsrechten, Live-Unterbrechung, menschlicher Übergabe und authentischem Termin-/Sales-Dossier.
- Gesprächs-/Meeting-Transkripte bei Einwilligung durch GTM-Rubriken und Post-Call-Tasks führen.
- Post-Sale-Onboarding, Bestandskunden-Expansion, Renewal-/Churn-Watchlists, wiederkehrende Auftragspfade.
- **Code Mode A/B** gegen reguläres MCP unter identischen Bedingungen für häufige Discovery-/Enrichment-Sequenzen; nur eindeutig bessere und sichere Variante einschalten.

**Done wenn** lizenzierte/erlaubte reale Voice-Sitzungen mit verifizierter Zuordnung, Abbruch- und Privacy-Gates sowie echter menschlicher Übergabe funktionieren und Code Mode einen unabhängig reproduzierbaren Vorteil zeigt **oder** bewusst verworfen wird.

**Donoren**: LiveKit, Vexa, GTM Superintelligence, Cloudflare Code Mode. Keine Pflicht zur Cloudflare-Dynamic-Workers-Produktionsmigration.

### Release 1.0.0 – Verkaufbare GreenGrapeMe-SaaS-Software

**Implementieren**
- Bedienbare vollständige Anwendung für Angebote/ICP, Discovery, Sales-Team, Work-Inbox, Kampagnen, Funnel, Gespräche, Termine, Deals, Umsatz und Mandantenadministration.
- Gesicherte Signup-/Org-/RBAC-/Billing-/Quota-/Audit-/Privacy-/Backup-/Migrationsfunktionen; Secrets und personenbezogene Daten ausschließlich in geeigneten Produktstores.
- Produktbetrieb, Monitoring, Alerts, Backups/Restore, Incident-/Support-Prozess, Dokumentation, Setup ohne CLI, vertragliche Transparenz bei Drittanbietern.
- Externe CRM/Calendar/E-Mail-/Payment-Adapter **nur für tatsächlich verkaufte Kernanforderungen**; vorhandene FruitStack-Adapter zuerst.
- Echtkunde kann sich registrieren, seinen Zielmarkt konfigurieren, eine autorisierte Sales-Mission starten, Ergebnisse prüfen und kostenpflichtig weiternutzen.

**Done wenn** externe, voneinander isolierte Pilotmandanten im Produkt ohne Administratorzugriff auf FruitStack-Crown-Jewels arbeiten; echtes Onboarding, Rechnungs- und Kündigungsprozesse geprüft sind; kritische Sicherheitstests, Backup/Restore, Betriebs-/Rechtscheck und zwei vollständige Sales-End-to-End-Fälle bestanden sind. „SaaS-ready“ ist kein Synonym für „Produktivverkauf belegt“.

## 8. Priorisierte offene Forschungs- und Entwicklungsfragen

**P0 – vor Integration weiterer Feature-Sets**
1. Tatsächliche installierte FruitStack-Builds und Host-Zugriffsrechte gegen die aktuellen Repository-APIs abgleichen. Kein angenommenes `AgentWorkProvider.execute()` oder nicht existentes MCP-Tool.
2. Pro Sales-Objekt eine Wahrheit/Owner entscheiden: Company identity (extern autorisiert), Discovery (StarFruitMe), Sales domain (GreenGrapeMe), Work authority (FruitStack), CRM-Export (Adapter).
3. Jurisdiktionsabhängige Kommunikation + Empfängersperren und konkreten Consent-/Rechtebeleg definieren. § 7 UWG: Werbung per E-Mail grundsätzlich vorherige ausdrückliche Einwilligung (enge Bestandskundenausnahme § 7 Abs. 3); B2B-Anrufe haben andere Voraussetzungen, automatisierte Anrufmaschinen gesonderte. Öffentliche Kontaktdaten sind kein Senderecht.
4. Testdatensatz mit echten, autorisierten Unternehmen und einem festen, manuell geprüften Golden Set erstellen: Falschtreffer, Mehrfachstandorte, Namensähnlichkeit, falsche Entscheider, tote Quellen.
5. Für proprietäre/AGPL-/GPL-Donoren Produkt-/Vertriebsrecht vor Codeübernahme klären und NOTICE-Kette erhalten.

**P1 – nach erster autonomen Sales-Mission**
6. Welche Gesprächs-/Voice-Runtime liefert die beste deutsche TTS/STT-Latenz und Verständlichkeit bei realen Kosten? LiveKit und bereits vorhandene FruitStack-/Python-Komponenten gegeneinander testen, nicht ungeprüft ElevenLabs voraussetzen.
7. Ob Signalgewichte aus tatsächlichen Abschlüssen lernen oder die beobachtete Selektionsverzerrung nur verstärken: Holdout-Design mit eingefrorenen historischen Signalen und eindeutigen Zeitfenstern.
8. Ist Cloudflare Code Mode gegenüber direktem MCP wirklich effizienter und genauso sicher? Keine Architekturentscheidung auf Marketingzahlen stützen.
9. Ist Autonnel tatsächlich die wirtschaftlichste Teilkomponente für *Lead-Qualifizierung* (nicht Checkout)? Auf Real-UX, Hosting-Kosten, Quellcode-Reife und Lizenz prüfen.
10. Differenzierte Kundenrechte und Datenaufbewahrung bei B2B-Personen/Marketing-Audits im deutschen Markt festlegen, inklusive Datenschutzinformationen und Lösch-/Auskunftswegen.

**P2 – vor breiter SaaS-Skalierung**
11. Einheitlicher Markt-/Produktpreis und tatsächliche Unit Economics (Kosten pro verifiziertem Account, zulässigem Touch, qualifiziertem Termin, gewonnenem Kunden; Deckungsbeitrag nach Provider-/Infrastruktur-/Supportkosten).
12. Lasttests für 10/100/1.000 Mandanten unter realen Discovery-, Modell- und Kommunikationsbudgets; kein unkontrolliertes Multi-Tenant-Sharing.
13. Internationalisierung der Kommunikations-/Einwilligungsregeln pro Rechtsraum; keine globale Default-Erlaubnis.

## 9. Abnahme, Metriken und Release-Disziplin

**Testpyramide:** Pure Contracts/State-Machines → Adapter-Contract-Tests → Reale Quelle bei autorisiertem Pilot → FruitStack-Work-/Effect-Test → negative Sicherheits-/Datenabgrenzungstests → vollständige, manuell unabhängige Vertriebsergebnis-Reconciliation.

**Release-Felder pro Gate:** Commit-SHA, Quell-/Donor-SHA, Legal/License-Entscheid, eingesetztes Modell, Testkohorte, verifizierte Quelle, Baseline, unabhängige Testergebnisse, Kosten, Grenzfälle, Rollback und Deploy-Nachweis. Ohne diese Evidenz nur `IMPLEMENTED_NOT_VALIDATED`, `INCOMPLETE` oder `NOT_STARTED` – kein „fertig“.

**Roadmap-Prinzip:** Nicht zehn neue Subsysteme für hypothetische Skalierung bauen. Erst jeden vollständigen Fachablauf mit einem realen Mandanten und genehmigten Datenquellen nachweisen. Bestehende FruitStack-Integrationen dürfen *nicht* ungefragt durch neue Runtime-Frameworks oder parallele Datenbanken verdrängt werden.

## 10. Quellenverzeichnis (Research zum 02.11.2026)

**Eigene, tatsächlich überprüfte Code-/Vertragsquellen**
- GreenGrapeMe PR #1: https://github.com/tonnestate/GreenGrapeMe/pull/1
- GreenGrapeMe bestehender Donorenstand: `docs/DONORS.md`; OpenOutbound-Übernahme: `docs/ADOPTION_OPENOUTBOUND.md`; Abnahmevertrag: `docs/ACCEPTANCE.md`.
- StarFruitMe MCP: https://github.com/tonnestate/StarFruitMe/blob/main/src/starfruitme/mcp_server.py; Handoff: https://github.com/tonnestate/StarFruitMe/blob/main/src/starfruitme/golden_handoff.py
- BlackberryMe MCP: https://github.com/tonnestate/BlackberryMe/blob/main/src/blackberryme/mcp_server.py; Remote Policy: https://github.com/tonnestate/BlackberryMe/blob/main/docs/REMOTE_COMMUNICATION.md
- KIGOR read-only MCP: https://github.com/tonnestate/KIGOR/blob/main/kigor/mcp_stdio.py; Status: https://github.com/tonnestate/KIGOR/blob/main/docs/26-GESAMTKONZEPT-STATUS-ROADMAP.md

**Externe primäre Technologie-/Donorquellen**
- Cloudflare Code Mode, 20.02.2026: https://blog.cloudflare.com/code-mode-mcp/
- Cloudflare MCP Code Mode, 27.10.2026: https://developers.cloudflare.com/agents/model-context-protocol/guides/build-codemode-mcp-server/
- Cloudflare Agents Runtime und Long-running, 27.–29.10.2026: https://developers.cloudflare.com/agents/concepts/agentic-patterns/long-running-agents/ und https://developers.cloudflare.com/agents/runtime/
- Cloudflare SDK Source/Lizenz: https://github.com/cloudflare/agents
- OpenOutbound Source/Approval/Signals: https://github.com/xyluxx/openoutbound, https://github.com/xyluxx/openoutbound/blob/main/docs/concepts/safety-and-approvals.md, https://github.com/xyluxx/openoutbound/blob/main/docs/concepts/signals.md
- AgentSDR Source und 08.10.2026 Release: https://github.com/Kandid-ai/AgentSDR und https://github.com/Kandid-ai/AgentSDR/blob/main/CHANGELOG.md
- Autonnel: https://github.com/autonnel/autonnel
- Nuraveda AI Sales Agent: https://github.com/Nuraveda/ai-sales-agent
- GTM Superintelligence: https://github.com/attentiontech/gtm-superintelligence
- Perspective AI Funnel, 23.06.2026: https://www.perspective.co/changelog
- UWG § 7: https://www.gesetze-im-internet.de/uwg_2004/__7.html

**Hinweis:** Lizenz- und Anbieterangaben sind an die jeweils geprüften Revisionen/Produktdokumente gebunden; kundenspezifische Nutzungsbedingungen, EU-/DE-Konformität und tatsächliche Integrationsfähigkeit müssen im vorgesehenen Betrieb separat validiert werden. Dieses Dokument spezifiziert *was zu bauen und zu beweisen ist*, nicht fiktiv bereits gebaute oder verkaufte Leistungen.


## 12. Implementierungsnachtrag – BlackberryMe und MangoMe (02.11.2026)

Die nachstehenden Punkte sind **Code-/Offline-Integrationsstand**, kein Nachweis produktiver Live-Provider.

- **BlackberryMe:** `src/greengrapeme/blackberry_bridge.py` nutzt die tatsächlichen MCP-Werkzeuge `blackberry_plan_company`, `blackberry_role_relevance` und optional `blackberry_resolve_company_identity`. Tenant-spezifische Recherchebelege und Rollenbewertungen gelangen in den Kontext der PlumMe-Sales-Mission. Identität des Discovery-Kandidaten bleibt **UNVERIFIED**, bis eine tatsächliche Account-Zuordnung nachgewiesen wurde; kein unkontrollierter Kontakt.
- **MangoMe:** `src/greengrapeme/mango_binding.py` bindet über den bestehenden, hostgeschützten `enter_work`-Vertrag eine SalesMission an MangoMes kanonische Projekt-/Family-/Plan-/Slice-Identität. Die Ergebnisdatenhaltung in GreenGrapeMe speichert **nur Referenzen**, keine kopierte Governance-/Assurance-Wahrheit. Ein vor dem Host-Aufruf persistierter Intent-Fence stoppt Duplikataufnahmen nach unklaren Effekten. Für den aktiven SaaS-Betrieb fehlen die nachgewiesene Host-Authentifizierung, richtige Mandantenarbeitsräume, der Live-Mongo-End-to-End-Test und der unabhängige Recovery-Prozess.
- **Offline-Vertragstests:** `tests/test_blackberry_bridge.py`, `test_blackberry_mission.py` und `test_mango_binding.py` prüfen Antwortvalidierung, Quellbindung, URL-Eingaben, Opt-outs, Replay, Tenant-Isolation, kanonische Referenzen und unklare Aufnahmeversuche.
- **Vorrangige nächste Abnahme:** Ein tatsächlich laufender FruitStack-Host muss StarFruitMe → BlackberryMe → PlumMe → MangoMe über echte, erlaubte Daten und einen identifizierten authentifizierten Operator durchführen. Der anschließende Schritt ist die echte Discovery-Oberfläche und danach der autorisierte Sales-Effect-Pfad, nicht ein weiteres generisches Agentenframework.

Keine automatische Mail/LinkedIn/Telefon-Kontaktaufnahme, kein live verifizierter Closer, keine Kunden-Umsatzverifikation oder freigegebene SaaS-Produktionsstufe.

## 13. Implementierungsnachtrag – bedienbare Discovery-Software (02.11.2026)

- `src/greengrapeme/discovery_catalog.py`: durchsuchbare, mandantenbezogene Ansicht der bereits importierten Opportunity-/Unternehmensdaten mit Such-/Offer-/Statusfilter, Evidenz, zeitlichem Kaufsignal-Score, Sperrstatus, BlackberryMe-Recherche, Aufgaben und Missionen. Keine zweite Company-Master-Datenbank.
- `src/greengrapeme/webapp.py` und `src/greengrapeme/web/`: lokaler Browser-Arbeitsplatz mit mandantenfestem Viewer, geheimnisgeschützter GET-API, restriktiven Browser-Headern und ohne Schreib-/Versandpfad. `cli serve` startet ausschließlich an Loopback. Es ist **keine produktionsfähige SaaS-Anmeldung**.
- `tests/test_discovery_product.py`: acht zusätzliche Offline-Vertragstests für Suche, Detail, Quellen, Mandantentrennung, Tokenpflicht, Read-only, Darstellung und sichere Eingabegrenzen.
- **Offene Kernlücke:** Das Web-Frontend kann einen bestehenden Quell-/Agentenprozess nur betrachten, noch keinen autorisierten Discovery-Job starten, überwachen oder validiert mit MangoMe/PlumMe vollständig ausführen. Ein SaaS-Kundensystem braucht echte Org-/Nutzerrechte, Betriebs-/Datenzugriffsgrenzen, TLS, Secrets, Recovery, Kontakterlaubnis und ein separates abgestimmtes Sales-Effect-Protokoll.

Erfolgsmaßstab für den nächsten Product-Gate: Ein echter, legal zulässiger Discovery-Job wird aus der Oberfläche gestartet, ausgeführt, den zugehörigen Firmendatensätzen und Rollenprüfungen zugeordnet, und der Endanwender sieht einen nachvollziehbaren Abschluss-/Fehlerstatus – **ohne** doppelte Datenwahrheit oder fingierte Sales-Umsetzung.


## 14. Implementierungsnachtrag – UI-gesteuerte Discovery-Missionen (02.11.2026)

- `src/greengrapeme/discovery_jobs.py`: tenantgetrennter, persistenter Jobstatus einschließlich Idempotenz, Bbox-/NACE-/Budgetvalidierung und vor externem Quellaufruf gespeichertem Create-/Run-Fence. Vorhandener StarFruitMe-Job lesend oder erlaubter neuer StarFruitMe-Job mit hart begrenztem `run_discovery_job`.
- `src/greengrapeme/webapp.py`: lokaler `POST /api/discovery-jobs` mit Auth-Token, Same-Origin, JSON-/Payload-Validierung und hostgebundenem Tenant; Statusabfragen lesend. Keine externe Wirkung im HTTP-Request.
- `src/greengrapeme/web`: Discovery-Auftragsformular für Angebot, ICP, NACE und Geo-Suchgebiet, Warteschlange und laufende Zustandsanzeige.
- `src/greengrapeme/cli.py`: separater, fortlaufender oder einmaliger Product-Worker; in autorisiertem Hostkontext kann er MangoMe-WorkAdmission und PlumMe-UNI-Ausführung nutzen.
- `tests/test_discovery_jobs.py`: 12 zusätzliche Offline-Vertragstests (positive und negative Rechte-, Recovery-, Source-, Host-/Missions-, HTTP- und Tenant-Pfade).
- **Nicht erledigt:** echter Installations-/Host-Live-Smoke über die vier FruitStack-Komponenten, obligatorische BlackberryMe-Rechtsträgerzuordnung, geplante Wiederholung/Suche/Änderungsmonitoring, SaaS-Authentifizierung, Effekt- und Revenue-Strecke. Kein produktiver Kundenkontakt, kein durchgängiges Closing.

Verbindliches Gate für 0.4.0 bleibt **realer hostautorisierter Discovery-Lauf mit überprüfbaren Quellen**, nicht eine erfolgreiche Testdouble-Ausführung. Dokument: `docs/DISCOVERY_MISSIONS_UI.md`.


## 15. Implementierungsnachtrag – geschützte Sales-Kohorten und BlackberryMe-Zwischenschritt (02.11.2026)

GreenGrapeMe bindet eine SalesMission nun an die **unveränderliche Menge tatsächlicher Accounts aus ihrem eigenen Discovery-Job**, einschließlich Quellfingerprint. Dadurch können andere Jobs für dasselbe Angebot die AI-Kontextbasis nicht unbemerkt verändern. Änderungen und Suppression blockieren die weitere KI-Ausführung; übergroße Kohorten werden offengelegt und nicht stillschweigend als komplett abgearbeitet gezählt.

Der Discovery-Worker besitzt einen eigenen, bewusst beschränkten **BlackberryMe-Research-Gate**, mit hostseitigem `GG_ENABLE_BLACKBERRY_RESEARCH=1`. Es wird ausschließlich das bereits existierende, lokale Planungswerkzeug für Quellen-/Rechtsträgerprüfung aufgerufen und das Ergebnis tenantbezogen persistiert. Ohne diese Recherche geht kein Discovery-Job zur MangoMe-Arbeitsaufnahme; selbst ein erfolgreich abgeschlossener Plan ist **keine verifizierte juristische Identität** und gewährt kein Senderecht. Unklare Provider-Antworten bleiben vor einem erneuten Aufruf gesperrt.

Nächster notwendiger Beweis: Source-authorisiertes, echtes StarFruitMe/BlackberryMe/MangoMe/PlumMe-Host-E2E, anschließend belastbare Firmenidentität, sichere Korrekturen/Reconciliation, Batch-Splitting und dann autonome erlaubte Campaign-/Setter-Effects.


## 16. Releasefortschritt: 26–100 Unternehmen vollständig in Sales-Batches (02.11.2026)

Der bisherige harte Stop bei mehr als 25 Unternehmen ist für **26–100 zurückgegebene Quellenkonten** durch eine dauerhaft gespeicherte, deterministische Aufteilung ersetzt. Jedes Teilpaket (maximal 25) besitzt eine eigene unveränderliche Account- und Source-Hash-Kohorte sowie eine eigene SalesMission-/MangoMe-/PlumMe-Zuordnung. Der übergeordnete Discovery-Auftrag wechselt erst nach **allen** erfolgreichen Teilergebnissen auf `REVIEW_READY`; ein ungeklärter Source-/Provider-/MangoMe-Effekt bleibt gesperrt. Es gibt keine fingierte globale Kundenkontakt- oder Rechtsträgerfreigabe. UI zeigt Batch-Anzahl und Fortschritt.

Implementiert: `discovery_batches.py`, `batch_runner.py` und die Integration in `discovery_jobs.py`; neue `tests/test_discovery_batches.py` testen 26 und 60 Unternehmen, Mandantentrennung, Weiterlaufen nach Neustart, Quellrevision, Suppression und unabhängige Neuron-Rollen. **100 ist das konfigurierte Maximum der bisherigen ersten Source-Leseseite**, nicht die Gesamtzahl möglicher Treffer. Für produktive Vollständigkeit fehlen genuine Pagination/Source-Cursor und alle bereits dokumentierten Host-, Identity-, SaaS-, Outreach-/Setter-/Closer-Gates.


## 17. Implementierungsnachtrag: source-aware Pagination und 1.000-Account-Grenze

Der konkrete StarFruitMe-MCP-v2-Vertrag `find_companies(job_id, limit, offset)` liefert `total_matching`, `offset`, `limit` und nach `candidate_id` sortierte Einträge. GreenGrapeMe liest alle benötigten Seiten, prüft Seitenmetadaten, erwartete/erhaltene Gesamtzahlen, Kandidaten-Duplikate, Detailreferenzen und die erste Seite erneut nach dem Ladevorgang. Es findet kein stilles Abschneiden bei 100 Kandidaten mehr statt. Discovery-Requests erlauben **bis zu 1.000** Account-Reads, verteilt in bis zu 40 geschützte 25er-Sales-Missionen.

Liegt `total_matching` über dem beauftragten Limit, wird vor jeder Detailübernahme auf `BLOCKED_SOURCE_CAPACITY` mit Quellgesamtzahl und `imported=0` geschaltet. Ändern sich Pagination oder Kandidaten während der Erfassung, wird der Auftrag mit `SOURCE_PAGINATION_INCONSISTENT` blockiert. Vollständigkeit innerhalb des gesetzten Limits ist das Ziel; das System behauptet **keine unlimitierte Quell-/Unternehmensabdeckung**. StarFruitMe hat derzeit keinen konsistenten Snapshot-/Cursor-Token über mehrere MCP-Calls – ein verbleibender technischer Release-Gate.

Mehr als 1.000 Kandidaten benötigen einen geplanten, versionierten Cursor-/Teilmengen-Workflow und eine verifizierte Quelle, bevor von einer vollständig abgeschlossenen Discovery gesprochen werden darf. Kein Outreach, kein Live-Host-E2E-Test, keine neuen SaaS-Rechte.


## 18. Host-Vertrag korrigiert und lesbarer FruitStack-Preflight (02.11.2026)

Bei der echten Upstream-Inspektion wurde ein bis dahin von Testdoubles verdeckter MangoMe-Integrationsfehler gefunden: `enter_work` erzeugt keine automatisch freigegebene Specification, sondern eine kanonische **WorkIdentity** mit **normative_baseline**; `spec=None` und `spec_admitted=False`. GreenGrapeMe erfordert jetzt diese tatsächliche WorkIdentity/Family/Project-Linie und Persistenzattribute, speichert nur belegte IDs und verwechselt eine lokale Autoritätsannotation nicht mit einem MangoMe-Provider-Receipt. `EXISTING_WORK_CANDIDATE` bleibt ohne bewusstes Reconciliation-/WorkRef-Verfahren blockiert.

Neu: `src/greengrapeme/host_preflight.py` als separat ausführbarer, standardmäßig **effect-freier** Diagnoselauf. Er prüft StarFruitMe ausschließlich an einer hostautorisierten vorhandenen Job-ID, BlackberryMe durch MCP-Toollisting, MangoMe durch API-/Workspace-Vertragsprüfung und PlumMe durch no-effect NeuronRequest/UNI-Schema. Die Probe meldet `ready_for_controlled_host_trial` nur bei vier PASS und immer `production_ready=false`. `tests/test_host_preflight.py` und aktualisierte Mango-/Discovery-Batch-Vertragstests sichern diese Grenze ab.

Die eigentliche Host-Abnahme bleibt **offen**, bis GreenGrapeMe in der realen FruitStack-Installation eine autorisierte Discovery und die anschließende Work-/Neuron-Ausführung mit echten Provider-Receipts ohne Fabrication nachweist. SaaS-Login/RBAC und Kampagnen/Setter/Closer wurden bewusst nicht vorgezogen.
