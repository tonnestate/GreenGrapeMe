# G5 – Gutschrift, Forderungskorrektur und echte Rückerstattung (Schema v7)

Eine Gutschrift ist **keine** Überweisung. Der neue Fachprozess `SalesCreditNotes` korrigiert die Forderung einer bereits unabhängig bestätigten Ausgangsrechnung, ohne einen fiktiven Geldfluss zu erzeugen.

## Durchgängiger Prozess

Die Rechnungsbasis stammt ausschließlich aus einem bestätigten Vertrag und einer unabhängig als ausgestellt bestätigten Rechnung. GreenGrapeMe speichert zunächst eine Gutschrift-Absicht (PREPARED) mit unveränderlichem Rechnungsbeleg, Dokumentreferenz, Begründungsreferenz, Betrag und Mandant. Es erfolgt weder ein Versand noch eine Bankaktion.

Eine unabhängig authentifizierte Accounting-Schnittstelle (IndependentCreditNoteSource.verify) muss die **wirklich ausgestellte** Gutschrift unter exakt denselben Bindungen bestätigen. Erst dann wird sie zu CREDITED_CONFIRMED. Falscher Vertrag, abweichender Mandant, Betrag, ursprüngliche Rechnung, Empfänger-Identität oder ein bereits verwendeter Providerbeleg führen zur Ablehnung. Mehrere Gutschriften dürfen in Summe den Originalrechnungsbetrag nicht überschreiten.

Das Rechnungssaldo wird anschließend aus Originalbetrag minus **bestätigten** Gutschriften gebildet. Offene Entwürfe verändern den Saldo nicht. Die Bestandteile werden unabhängig gespeichert:

- ursprünglicher Rechnungsbetrag;
- tatsächlich bestätigter Gutschriftbetrag und verbleibende Rechnungsforderung;
- unabhängig bestätigte Bruttozahlungen;
- unabhängig bestätigte Rücküberweisungen;
- Nettozahlungseingang, Restforderung und gegebenenfalls Erstattungsanspruch.

Eine vollständig gutgeschriebene, noch nicht bezahlte Rechnung ist CREDITED – **nicht bezahlt**. Ist nach einer Gutschrift mehr Geld eingegangen als noch geschuldet wird, ist der Rechnungsstatus REFUND_DUE und der offene Erstattungsbetrag positiv. Eine Erstattung wird erst im bestehenden `SalesInvoices.settlement(..., direction='REFUND')` mit einem separaten echten Bank-/Accounting-Beleg verbucht. Danach wird der Status erneut bestimmt. Das System verschiebt kein Geld und löst keine automatischen Erstattungen aus.

Neuer Zahlungseingang kann den nach Gutschrift korrigierten Rechnungsbetrag nicht übersteigen. Dieselbe Gutschriftreferenz und dieselbe bestätigte Providerbelegidentität sind mandantenweit eindeutig und dürfen nicht erneut geltend gemacht werden. Die Prüfung der Rechnung, des Vertrags und aller bestätigten Gutschriften erfolgt vor und nach der unabhängigen Providerabfrage; bei Zeitkonflikten oder Quellenrevisionen wird kein neuer Gutschriftstatus übernommen.

## Schnittstellen- und Beweisgrenzen

`IndependentCreditNoteSource` ist ein vom Host kontrollierter Integrationsvertrag, keine installierte Live-Anbindung an ein Rechnungsprogramm. Der tatsächliche Provider muss aus seinem eigenen Datenbestand Beleg, Ausstellungszeitpunkt und Authentizität verifizieren. Reine KI-Aussagen, Kundenformularwerte und selbst gemeldete CRM-Ereignisse sind kein unabhängiger Beleg.

Der bestätigte Gutschriftbetrag beeinflusst **die Rechnungsforderung**, nicht bereits erhaltenes Kundengeld, den Plattformumsatz oder die tatsächlich geleistete Rückerstattung. Das vorhandene PilotLedger behält nur unabhängig bestätigte Ein- und Auszahlungen; so entstehen keine künstlichen Umsätze.

Die Datenbankmigration auf v7 ist additive Copy-forward-Migration. Bestehende Versionen v0–v6, Kundendaten, irreversiblen Provider-Versandversuche, Aufträge, Rechnungen, Bankbelege und Verträge bleiben unverändert. Die Datenbank-/Backup-Verifikation prüft die eindeutigen Gutschriftbelege; das Release-Audit zählt Entwürfe und bestätigte Gutschriften getrennt.

## Prüfungen und noch offene Produktionsreife

Die automatisierten Regressionen decken vollständige und partielle Gutschriften, bereits bezahlte Rechnungen mit Rückzahlungsanspruch, bestätigte Rückerstattung, gefälschte Providerantworten, überhöhte kumulierte Gutschriften, Replay/Neustart, unveränderliche Referenzen und Quellenänderungen während der Providerprüfung ab.

Es werden keine echten Gutschriften ausgestellt, keine Rechnungen versendet und keine Überweisungen ausgeführt. Die reale Accounting-/Bank-Anbindung sowie andere FruitStack-Fach- und Betriebsanforderungen bleiben bis zum erfolgreichen technischen Integrationsnachweis offen. Erfolgreiche isolierte Tests allein begründen keine Produktionsreife.
