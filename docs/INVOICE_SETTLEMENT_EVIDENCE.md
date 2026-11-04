# G5: Rechnung, Zahlung, Teilzahlung und Rückerstattung (Schema v6)

GreenGrapeMe erstellt jetzt ausschließlich lokale Rechnungsabsichten, die an einen **unabhängig bestätigten Vertrag** und dessen unveränderliche EUR-Konditionen gebunden sind. Der fachliche Baustein ist SalesInvoices. Es wird keine Rechnung automatisch versandt und keine Zahlung ausgelöst.

## Prozess und fachliche Invarianten

- Für jeden bestätigten Vertrag ist genau eine Einrichtungsrechnung (SETUP, Periode once) und eine Monatsrechnung je YYYY-MM möglich. Die Beträge werden ausschließlich aus den unveränderlichen, bestätigten Vertragskonditionen übernommen.
- Eine Rechnungsabsicht (PREPARED) ist kein Beleg für eine ausgestellte Rechnung. Erst die read-only-Prüfung über IndependentInvoiceSource mit Status ISSUED, exaktem Vertragsbezug, Betrag, Währung und eindeutiger Provider-Receipt führt zu ISSUED_CONFIRMED.
- Teilzahlungen und Rückerstattungen entstehen ausschließlich über IndependentCashSource nach Prüfung eines echten Bank- oder Accounting-Belegs. Der Provider muss den exakten Mandanten, Vertrag, Rechnung, Betrag, Bewegungstyp und Zeitpunkt bestätigen.
- Jede Geldbewegung wird gemeinsam mit dem SOURCE_CONFIRMED-Ereignis im vorhandenen PilotLedger in **einer** SQLite-Transaktion gespeichert. Für Kundenzahlungen wird CUSTOMER_PAYMENT_RECEIVED verwendet; Rückerstattungen werden separat als CUSTOMER_REFUND_PAID geführt.
- Eine Zahlung darf die noch offene Rechnungssumme nicht überschreiten. Eine Erstattung darf den tatsächlich eingegangenen Nettobetrag nicht überschreiten. Gleiche Belege können nicht mehreren Rechnungen oder Mandanten desselben Tenants zugeordnet werden. Idempotente Wiederholungen buchen nicht erneut.
- Die Rechnung zeigt ihren Saldo als UNPAID, PARTIALLY_PAID oder PAID an. Ein vollständig bezahlter Betrag kann durch eine belegte Rückerstattung wieder teilweise offen werden. Bruttozahlung, Rückerstattung und Nettozufluss werden separat ausgewiesen.

Die vorhandene PilotLedger-Zusammenfassung enthält nun client_refund_confirmed_cents und client_net_payment_confirmed_cents. Die Commercial-Reconciliation liefert customer_refund_confirmed_cents und customer_net_settled_cents. Kundengeld ist nicht automatisch Plattformumsatz oder Deckungsbeitrag; weitere Providerkosten, Forderungsausfälle, Steuern und externe Zuordnungen müssen gesondert nachgewiesen werden.

## Autorisierte Host-Anbindung

Die beiden Quellen IndependentInvoiceSource und IndependentCashSource sind explizite Schnittstellen für den **vertrauenswürdigen, unabhängig authentifizierten FruitStack-Host**. Sie sind keine lauffertigen Bank-, Stripe- oder Rechnungsanbieter-Verbindungen und dürfen nicht durch Kundenformular- oder Modellantworten ersetzt werden.

Der Host muss die ausgegebene Rechnung, Signatur- und Vertragsbindung, Banktransaktion, Verwendungszweck, eventuelle Teilerstattungen und Geschäftspartner über den tatsächlich integrierten Dienst verifizieren. Für die Unterscheidung von echten Bankbuchungen und bloß gemeldeten CRM-Zahlungen bleibt der Source-Confirmation-Nachweis Pflicht.

Die neue Datenbankversion v6 wird explizit neu initialisiert oder mit dem nicht überschreibenden Copy-forward-Migrationspfad hergestellt. Ein bestehender v0–v5-Datensatz behält seine alten Kunden-, Buchungs-, Vertrags- und Versand-Ereignisse. Neue Invoice-/Cash-Receipt-Fences werden in Datenbank-Backups auf Schema und Unique-Indizes geprüft.

CI führt die vollständigen fachlichen SQLite- und Regressionstests einschließlich Teilzahlung, Erstattung, Überzahlung, Doppeltbuchung, falscher Source-Receipt und Neustart aus. Es entstehen keine realen Rechnungen oder Überweisungen. **Die eigentliche betriebsfertige Anbindung an Bank-, Accounting- und Vertragssysteme sowie der übrige FruitStack-End-to-End-Nachweis sind weiterhin für die Produktionsreife erforderlich.**
