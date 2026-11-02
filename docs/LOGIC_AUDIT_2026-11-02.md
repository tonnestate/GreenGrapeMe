
# GreenGrapeMe – Logik-Audit vom 02.11.2026

**Gegenstand:** Business-Sales-Queue, StarFruitMe-Discovery-Status, MangoMe-WorkIdentity, PlumMe-Ergebnisannahme. Abgleich mit tatsächlichen StarFruitMe- und MangoMe-Quellverträgen. GitHub-CI-Tests nutzen für die Provider Testdoubles, keine echten Hostaufrufe.

## Behobene P0-Fehler

**1. Falscher Discovery-Abschluss.** StarFruitMe führt mit `run_discovery_job(max_searches)` nur einen begrenzten Teil der geplanten Aufgaben aus und gibt im Status `job_state` zurück. GreenGrapeMe behandelte schon einen erfolgreichen Aufruf als `SOURCE_DONE`. Neu: nur `COMPLETED_NO_KNOWN_GAPS` führt zum Import. `IN_PROGRESS`, `COMPLETED_WITH_GAPS` und fehlende oder inkonsistente Statusangaben führen zu `BLOCKED_SOURCE_COVERAGE` und null importierten Kandidaten. Dies bestätigt nur die geplanten StarFruitMe-Tasks, nicht die tatsächliche Vollständigkeit aller existierenden Firmen.

**2. MangoMe-Dublettenprüfung bei Sales-Batches.** Jeder Batch übergab den gleichen Nutzerauftrag ohne `work_ref` an MangoMe. Die echte Steuerung liefert bei erneutem normalisiertem Auftrag `EXISTING_WORK_CANDIDATE` statt einer neuen autorisierten WorkIdentity. GreenGrapeMe verwendet nach dem ersten Batch dessen bereits persistent gebundene WorkIdentity als ausdrücklichen `work_ref` für weitere Pläne/Slices. Erwartet wird `EXISTING_WORK_BOUND` mit gleicher WorkIdentity. Fehlende, widersprüchliche oder unklare Kanonizität verhindert die Weiterverarbeitung. Unabhängige Discovery-Aufträge werden nicht stillschweigend verbunden.

**3. TOCTOU zwischen Neuron-Lauf und Speicherung.** Die Account- und Suppression-Prüfung erfolgte nur vor der PlumMe-Ausführung. Ein zwischenzeitlicher Opt-out oder Quellwechsel ließ die nachträgliche Speicherung eines veralteten Vorschlags zu. Neu: Erneute vollständige Quell-Hash-/Suppression-Prüfung innerhalb der gleichen Schreibtransaktion, in der ein Neuron-Ergebnis übernommen würde. Abweichung ergibt `SOURCE_INVALIDATED` und `BLOCKED_SOURCE_REVISION`, ohne einen akzeptierten Vorschlag zu speichern. Die Modellkosten können trotzdem angefallen sein.

## Testevidenz

Regressionstests simulieren offene/fehlerhafte Quellenjobs, fehlende Abschlusszustände, den zweiten MangoMe-Batch mit expliziter WorkIdentity, ungültige WorkRefs sowie Opt-out und Quellenänderung **während** der Neuron-Ausführung. Bestehende Discovery-, Batch-, Tenant- und Recovery-Tests laufen weiterhin.

## Weiter offene Abnahme- und Betriebsrisiken

1. **Echter Host-End-to-End-Test fehlt.** Vor produktiven Aussagen sind echte StarFruitMe-, BlackberryMe-, MangoMe- und PlumMe-Receipts unter autorisierten Provider-/Workspace-Konfigurationen erforderlich.
2. **StarFruitMe hat keinen transaktionalen Snapshot über mehrere Seiten.** First-Page-Recheck, Hashes und Counts begrenzen, aber beseitigen nicht alle Änderungsrennen. Mehr als 1.000 Kandidaten pro Discovery benötigen versionierte Suchfenster.
3. **Blockierte Jobs brauchen ein autorisiertes, explizites Reconciliation- und Resume-Verfahren.** Unklare Quell-, BlackberryMe- oder MangoMe-Effekte dürfen nicht automatisch wiederholt werden.
4. **BlackberryMe-Rechercheplanung ist keine Rechtsträger- oder Personenverifikation.** Keine verdeckte Aufwertung zu Kontaktdaten- oder Versandberechtigung.
5. **Produktive SaaS-Authentifizierung, rechtmäßige Campaign-/Setter-/Closer-Effekte und RevOps-Umsatzbelege fehlen.** Der lokale Viewer-Token und Operator-Env-Flags sind keine öffentliche Multi-Tenant-Sicherheitslösung.

**Fazit:** Drei konkrete P0-Logikfehler sind korrigiert und offline regressionsgetestet. Das ersetzt keine echte Provider-/SaaS-Abnahme und legitimiert keine automatischen Kundenkontakte.


## Zusätzlich behobener Datenintegritätsfehler – gemischte Quell-Charge

**Vorher:** Der bisherige `SalesWorkspace.ingest` importierte Datensätze der Reihe nach. Wenn ein Batch neue Firmen und zugleich eine abweichende Version einer vorhandenen Firma enthielt, wurden neue Firmen schon dauerhaft importiert, bevor GreenGrapeMe den späteren Konflikt erkannte und den Parent-Job blockierte. Das führte zu Teilbeständen außerhalb der akzeptierten Discovery-Mission.

**Nachher:** `ingest` materialisiert die Batch-Eingabe und prüft bei `BEGIN IMMEDIATE` alle eingehenden Identitäten/Quell-Payloads vor dem ersten Import. Jede Abweichung einer bestehenden Opportunity oder konkurrierende Payloads für dieselbe neue ID lehnen die gesamte Batch-Insertion atomar ab. Bestehende Firmen erhalten einen Konflikt-Audit-/Prüfdatensatz; neu auftauchende IDs ohne gespeicherte Firmenakte erzeugen keinen verwaisten Review-Task. Rückgabe: `new=0` und eine positive Konfliktanzahl. Zwei zusätzliche Regressionstests decken Mischchargen und mehrfach widersprüchliche Neu-IDs ab.

Diese atomare Vorprüfung ist nötig, damit ein wegen Identitätskonflikten abgelehnter Auftrag keine stillen neuen Opportunities in den Vertriebsdaten zurücklässt.
