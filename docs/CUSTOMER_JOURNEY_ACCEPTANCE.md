# GreenGrapeMe – fachliche End-to-End-Abnahme (Vertriebsauftrag)

## Produktversprechen und Abnahmeeinheit

Eine Abnahme muss sich an einer **Kundenreise pro Vertriebsauftrag** messen
lassen, nicht an isolierten Tabellen oder einer hohen Testanzahl. Für einen
Pilot mit festgelegtem Angebot, Preis und Zielgruppe muss sich ein einzelner
CRM-Vorgang vom nachweisbaren Ursprung bis zum tatsächlich bestätigten
Zahlungseingang verfolgen lassen.

`SalesJourney.get(tenant,pilot,case)` ist eine rein **lesende Projektion** auf
die bestehenden CRM-, Nachrichten-, Kalender-, Vertrags-, Rechnungs-, Bank-
und Gutschriftenregister. Sie erstellt **keine neue CRM-Datenbank, keinen
zweiten Scheduler und keine neuen externen Effekte**. Alle Daten werden unter
einer zusammenhängenden SQLite-Lesetransaktion erfasst.

Im geschützten CRM-Cockpit ist der Verlauf per Pilot-ID und Vorgangs-ID
aufrufbar. Der dazugehörige REST-Endpunkt heißt
`GET /api/pilot-journey?pilot=<id>&case=<id>`, mit
aktuell geprüftem OIDC-/Mandantenzugriff und rein lesenden Rechten.

## Fachliche Evidenzklassen

| Phase | Was das System belegen darf | Was es nicht behaupten darf |
| --- | --- | --- |
| Discovery | Ein recherchierter Prospect mit Quellennachweis | Kundenanfrage, Einwilligung oder Kundenidentität |
| Inbound | Eine vom Operator gemeldete Anfrage mit Quellenreferenz | Independently verifizierte Identität oder Kontaktberechtigung |
| Kommunikation | Vorbereitet, Provider angenommen, tatsächlich per GET zugestellt | Annahme = Zustellung, Öffnung = Erfolg |
| Kalender | Terminabsicht oder unabhängiger Provider-Buchungsbeleg | Terminbuchung = wirklich stattgefundenes Gespräch |
| Gespräch und Angebot | Vom Vertrieb gemeldeter CRM-Meilenstein | Extern verifizierter Gesprächs-/Zustellnachweis |
| Vertrag | Independently geprüfte Signatur mit eingefrorenen Vertragskonditionen | Unbezahlter Vertrag = Umsatz |
| Rechnung | Provider-bestätigte Rechnungsstellung | Rechnung = realer Zahlungseingang |
| Bank | Confirmed Zahlung und getrennt bestätigte Erstattung | Kunden-Geldeingang = GreenGrapeMe-Plattformumsatz oder kausal verursachter Mehrumsatz |

Die Finanzsummen berücksichtigen nur tatsächlich providerbestätigte
Rechnungen, Gutschriften und Bankbewegungen aus demselben CRM-Vorgang.
`customer_net_cash` ist **kein** Plattformumsatz, **kein** Gewinn und
**kein** Beweis für durch GreenGrapeMe verursachten Mehrumsatz.

Die angezeigte nächste Aktion ist eine **Empfehlung zur fachlichen
Prüfung**, niemals eine Versand-, Kalender- oder Zahlungsautorisation.
Suppression und veränderte Quellen werden als eigene Blocker ausgewiesen.

## In CI geprüfte, vollständige lokale Kette

`tests/test_customer_journey_e2e.py` prüft mit der *tatsächlichen*
GreenGrapeMe-Persistenz und den vorhandenen Modulen:

1. Realer Pilot und als inbound gemeldeter CRM-Vorgang.
2. Manuelle Qualifizierung; vorbereitete Antwort ist **nicht** zugestellt.
3. Lokale Terminabsicht und stubbed, separat bestätigte Kalenderbuchung –
   **nicht** automatisch als stattgefundenes Gespräch.
4. Vom Operator gemeldetes Meeting und Angebotsübergabe.
5. Echte Vertrags-Domainlogik mit abgefangener Host-Approval und
   abgefangenem Signatur-Provider; CRM-/Ledger-Update gemeinsam.
6. Rechnungsstellung mit abgefangener Accounting-Bestätigung.
7. Zahlung mit abgefangener Bankbestätigung; vorher null bestätigter Cash.
8. Gleicher Stand nach Datenbank-Neustart, ohne doppelte Umsatzverbuchung.
9. Mandantenisolation, Sperre unbekannter Vorgänge und dauerhaftes NO-GO
   ohne echte Live-Providerabnahme.
10. Negativstrecke: Discovery-Prospect wird **nicht** zum simulierten
    Inbound-Lead, darf nicht über Inbound-Reply senden und ohne
    Vertriebsprozess keinen Vertrag erhalten.

Die OIDC-/API- und Browserregression prüft die sichere Bereitstellung
dieser Vertriebsakte im geschützten CRM.

**Wichtig:** `ConfirmedCalendar`, `ApprovedQuote`, `SignedDocument`,
`IssuedAccountingInvoice` und `ConfirmedBankSettlement` sind ausschließlich
Offline-Testdoubles für die echten Verifikationsprotokolle. Sie greifen
keinen Provider an und sind **keine Live-Abnahme**.

## Fachliche NO-GO-Liste für einen ersten zahlenden Kunden

- **G1:** Für den kundenspezifischen Auftrag muss Discovery mit echter,
  rechtmäßig nutzbarer Quelle und belegter Trefferqualität laufen.
- **G2:** Der rechtlich zugelassene Kommunikationskanal muss mit echten
  Kundenbelegen, Suppression und unabhängiger Zustellung getestet sein.
  Discovery alone ist kein Kontaktauftrag.
- **G3:** Der echte Terminanbieter muss Buchung, Einladungen,
  Stornierungen und eine separate Teilnahme-/No-show-Behandlung liefern.
- **G4:** Tatsächlich freigegebene Angebote und Signaturen müssen gegen
  einen realen Anbieter und die CRM-Quellenbindung abgenommen werden.
- **G5:** Die Rechnungsausgabe und der Bank-/PSP-Abgleich müssen an
  produktiven bzw. verifizierten Pilotkonten nachgewiesen werden.
- **Ops:** Identität, Rollen, Schlüsselwechsel, Alarmierung, Restore,
  Dokumentation und Datenschutz müssen auf der ausgerollten Instanz geprüft
  sein.
- **Kommerzialisierung:** Das Pilotprojekt muss Wert und wiederkehrende
  Zahlungsbereitschaft belegen. Ein einmaliger, stubbed Bankbeleg ersetzt
  keine Kundenbindung, Retention oder nachgewiesene Wirtschaftlichkeit.

Diese Liste darf nicht durch das Bestehen lokaler Tests als erledigt
gekennzeichnet werden. Das bestehende `release-audit` bleibt NO-GO.
