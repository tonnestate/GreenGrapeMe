# G4/G5 — Verbindliche Vertragskündigung und Fakturierungsstopp (Schema v8)

## Geschäftsregel

Ein unterschriebener Vertrag ist in GreenGrapeMe bislang dauerhaft abrechenbar geblieben. Ein bloßes CRM-Statusfeld ist jedoch kein rechtsverbindlicher Kündigungsnachweis. Die neue Komponente `SalesTerminations` speichert deshalb nur **unabhängig vom vertrauenswürdigen Vertragsdienst bestätigte** Kündigungen mit Vertrags-, Kunden-, Signatur-, Referenz-, Mandanten- und Wirksamkeitsbindung.

`SalesTerminations.reconcile(..., source=IndependentTerminationSource)` prüft den unveränderten signierten Vertrag, dessen Preis- und Herkunftsbindung sowie einen eigenständigen Kündigungsbeleg vom Typ `CONTRACT`. Der Provider muss `CANCELLATION_ACCEPTED` bestätigen und das exakte Wirksamkeitsdatum zurückgeben. Der Kündigungsbeleg darf nicht mit einer ursprünglichen Signatur verwechselt oder einem anderen Vertrag/Mandanten zugeordnet werden. Es gibt genau eine bestätigte Kündigung pro Vertrag; konkurrierende oder abweichende Änderungen benötigen eine fachliche Reconciliation.

`SalesTerminations.status` unterscheidet ohne künstliche Folgetransaktion `TERMINATION_SCHEDULED` und `TERMINATED` anhand der unabhängig bestätigten Wirksamkeit.

## Finanzielle Rückabwicklung

Sobald die Kündigung bestätigt ist, dürfen neue Ausgangsrechnungen für den Wirksamkeitsmonat und alle späteren Monate nicht mehr angelegt werden. Eine bereits angelegte, aber noch nicht als ausgestellt bestätigte Rechnung darf ebenfalls nicht mehr bestätigt werden, wenn ihr Monat davon betroffen ist. Bei untermonatiger Kündigung wird **keine erfundene Vollmonatsforderung oder automatische anteilige Gutschrift** erzeugt: der Wirksamkeitsmonat wird bewusst zur Klärung blockiert. Wegen eines möglicherweise anders lautenden Vertrags-/Abrechnungszeitzonenbezugs werden die Monatsgrenzen konservativ beurteilt.

Bereits ausgestellte Rechnungen bleiben zugänglich. Die Komponente `SalesCreditNotes` kann weiterhin unabhängig belegte Gutschriften erzeugen. Ein tatsächlicher Zahlungseingang wird unabhängig über `SalesInvoices.settlement` verbucht; offene Rückzahlungen werden bis zum separaten Bankbeleg als `REFUND_DUE` ausgewiesen. **Eine Vertragskündigung löscht weder einen historischen Vertragsabschluss noch einen echten Zahlungseingang und verschiebt kein Geld.**

Wiederholte identische Kündigungsnachweise sind idempotent. Änderungen des Vertrags oder der bestätigten Quellen während der externen Prüfung führen zum Abbruch vor der Speicherung. Der Status wird nur aus bestätigtem Providerbeleg abgeleitet, nicht aus einer KI-Aussage, einer CRM-Aktion oder einer HTTP-Anfrage vom Kunden.

## Integration und Release-Grenzen

Schema v8 ist auf neu angelegten operativen Datenbanken initialisiert und wird für ältere Versionen ausschließlich über die bestehende Copy-forward-Migration hergestellt. In Backup-/Restore-Prüfungen werden die eindeutige Kündigungs-ID und der eindeutige Providerbeleg geprüft. Das Release-Audit trennt geplante und bereits wirksame, unabhängig nachgewiesene Kündigungen.

Die automatisierten fachlichen Tests prüfen, dass ein bestätigter Kündigungsnachweis spätere Rechnungen verhindert, ältere Abrechnungsfälle weiterhin für Gutschrift und Rückerstattung zugänglich bleiben, unbestätigte Providerantworten keine Kündigung auslösen und Quellendrift oder wiederverwendete Belege nicht zu doppelten Kündigungen führen.

**Produktionsreife wird damit noch nicht behauptet:** `IndependentTerminationSource` ist eine Host-Schnittstelle und muss mit dem tatsächlichen Vertrags-/Signaturdienst authentifiziert verbunden werden. Eine externe Kündigung wird durch diese Bibliothek **nicht** ausgelöst. Auch der reale Accounting-/Bank-Belegpfad sowie der übrige Vertriebs- und SaaS-End-to-End-Nachweis sind weiterhin notwendig.
