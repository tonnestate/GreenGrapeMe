# GreenGrapeMe – öffentliche Landingpages, SEO, GEO und Vertrauensnachweise

## Zweck und Architektur

Der geschützte SaaS-Arbeitsbereich war bisher auf `/` ausschließlich eine
OIDC-Loginmaske. Das ist **keine** geeignete öffentliche Produktseite.
Deshalb gibt es nun eine **separate, statisch gerenderte öffentliche
WSGI-Anwendung** mit eigenem HTTPS-Origin, ohne Login, Kunden-API, Cookies,
Marketing-Tracker oder externen Assets:

- `/` – zentrale B2B-Produkt-Landingpage mit klarer Zielgruppe, Prozess und Pilot-CTA
- `/lead-recherche` – Quellen, ICP und Grenzen der Unternehmensrecherche
- `/vertriebsautomatisierung` – Qualifizierung, Rechteprüfung und Antwortversand
- `/crm-vertriebsakte` – Customer Journey und einheitlicher Nachweisstatus
- `/termine-vertraege` – Buchung, Anbieterbeleg, Angebot und Signatur
- `/umsatznachweise` – Rechnung, Bank, Gutschrift und ROI-Grenzen
- `/pilotprojekt` – definiertes Pilotangebot ohne erfundene Preise
- `/methodik` – redaktionelle Quellen-/Prüfmethodik und Testgrenzen
- `/sicherheit` – tatsächliche Sicherheitsmechanismen und offene Audits
- `/ueber-uns` – Zweck, Transparenz und verantwortlicher Betreiber
- `/fragen` – sichtbare, kontextbezogene Fragen und Antworten
- `/kontakt` – erreichbarer, verbindlich konfigurierter Betreiber

Diese Seiten sind **eine Website**, keine neuen Einzelprojekte oder Domains.

Die Marketing-Anwendung wird aus `greengrapeme.marketing_site` erzeugt.
Der SaaS-Host bleibt separat mit OIDC/JWT, Mandanten-Headern und
`Cache-Control: no-store`. SSO-Seiten/Assets tragen nun ausdrücklich
`X-Robots-Tag: noindex, nofollow, noarchive`.

## Vor dem Start zwingend echte Betreiberinformationen setzen

Die Anwendung startet ohne diese sechs Felder **nicht**:

| Variable | Zweck |
|---|---|
| `GG_PUBLIC_ORIGIN` | Wirklicher HTTPS-Origin der Marketing-Website, ohne abschließenden Slash |
| `GG_PUBLIC_OPERATOR_NAME` | Rechtlich verantwortlicher, verifizierter Betreibername |
| `GG_PUBLIC_CONTACT_EMAIL` | Tatsächlich erreichbare öffentliche Kontakt-E-Mail |
| `GG_PUBLIC_IMPRINT_URL` | HTTPS-URL zu einem **vorhandenen, rechtlich geprüften** Impressum |
| `GG_PUBLIC_PRIVACY_URL` | HTTPS-URL zur **tatsächlichen** Datenschutzerklärung |
| `GG_PUBLIC_APP_URL` | HTTPS-URL der separat gesicherten SaaS-Anmeldung |

Die URLs werden syntaktisch validiert. Ein HTTP-200-Check externer Seiten,
eine Prüfung ihrer rechtlichen Vollständigkeit oder eine Verifikation des
Postfachbesitzes kann daraus **nicht** abgeleitet werden. Die Konfiguration
ist ein notwendiger, nicht hinreichender Deployment-Gate.

Beispiel eines WSGI-Starts **nach** Bereitstellung verifizierter
Umgebungsvariablen und HTTPS-Terminierung:

```bash
gunicorn 'greengrapeme.marketing_site:create_marketing_service_from_env()' --bind 127.0.0.1:8081
```

Der Reverse Proxy muss `wsgi.url_scheme=https` ausschließlich nach
geprüfter TLS-Terminierung setzen. Nicht per ungeprüftem
`X-Forwarded-Proto` aus dem Internet durchreichen. Kein gemeinsamer
WSGI-Origin mit der SaaS-API.

## Durchgängige Conversion: Landingpage → Pilotanfrage → Operator → CRM

Die Pilotprojekt-Seite enthält bei vollständig konfiguriertem öffentlichen
Dienst ein echtes HTML-Formular (Unternehmen, Geschäfts-E-Mail, begrenztes
Anliegen und Kenntnisnahme der verlinkten Datenschutzhinweise). Es ist
barrierearm ohne JavaScript und ohne Drittanbieter-Tracker nutzbar.

`POST /pilot-anfrage` ist ausschließlich same-origin,
`application/x-www-form-urlencoded`, auf **3.000 Bytes** begrenzt und
fordert ein kurzlebiges HMAC-signiertes Formular-Token. Wiederholungen
desselben Formulars werden nicht erneut gespeichert. Duplicate-Felder,
fremde Origins, ungültiges UTF-8, nicht bestätigte Datenschutzhinweise,
Honeypot-Spam und übermäßige Einreichungen werden abgewiesen bzw. sicher
begrenzt. Die Erfolgsmeldung enthält keine personenbezogenen Daten, ist
`noindex` und wird nicht zwischengespeichert. Die indexierbare
Pilotprojekt-Seite mit einem frischen Formular-Token hat
`Cache-Control: no-store` und darf nicht per CDN statisch gecacht werden.

**Besonderes Sicherheitsmerkmal:** Der öffentliche Webprozess hat **keinen
Zugriff auf die operativen CRM-, Zahlungs- oder Mandantendatenbanken**.
Die Anfragen werden ausschließlich in einer separaten, explizit
provisionierten SQLite-Datei mit eingeschränkten Dateirechten gespeichert.
Ein Eintrag ist zunächst `NEW`, weder verifizierte Unternehmensidentität
noch Einwilligung zu Werbung.

### Einrichtung auf einem echten Host

1. Betreiber/Datenschutz-URLs und Domain müssen gemäß obiger
   Konfiguration vollständig vorliegen.
2. Separate Datei, **nicht** die operative SaaS-SQLite-Datei:
   `python -m greengrapeme.cli --db /srv/gg/public-inquiries.sqlite public-inbox-bootstrap`.
   **Verbindliches OS-Gate:** Den öffentlichen Dienst unter einer eigenen,
   unprivilegierten Benutzeridentität betreiben, die weder die operative
   `GG_SAAS_DB` noch deren Backups, Schlüssel oder Verzeichnisse lesen
   darf. Dem SaaS-Dienst ausschließlich den benötigten Zugriff auf
   die getrennte Inbox (einschließlich SQLite-Journaldateien und
   Verzeichnis) über gezielte Dateisystem-ACLs erteilen. Die beim
   Bootstrap gesetzten Dateirechte `0600` sind lediglich der sichere
   Ausgangszustand. Ein gemeinsames Dienstkonto würde diese Isolation
   **nicht** gewährleisten.
3. Öffentlicher WSGI-Prozess benötigt zusätzlich
   `GG_PUBLIC_INBOX_DB` (genau diese Datei),
   `GG_PUBLIC_INQUIRY_TENANT` (fest zugeordneter SaaS-Mandant) und
   `GG_PUBLIC_FORM_KEY` (starker zufälliger, geheimer Server-Schlüssel
   mit mindestens 40 druckbaren Zeichen). **Nicht in Git oder Browser
   ausgeben.** Für mehrere öffentliche Domains eigene Inbox/Schlüssel.
4. Der OIDC-geschützte SaaS-Prozess benötigt nur
   `GG_SAAS_PUBLIC_INBOX_DB` (dieselbe separate Datei) und
   `GG_PUBLIC_INQUIRY_TENANT`. Der Formularschlüssel gehört **nicht**
   in den SaaS-Prozess. Der Zielmandant muss existieren und Operatoren
   mit Serverrollen versehen sein.
5. Im CRM erscheint für berechtigte Operatoren eine eigene Warteschlange
   für öffentliche Anfragen. `ADOPT` bindet eine Anfrage nach manueller
   Prüfung an einen bereits existierenden Pilot. `DECLINE` lehnt sie ohne
   CRM-Erstellung ab. Die Übernahme verwendet die bestehende
   `PilotSalesFlow.open_inbound`-Fachlogik mit Ursprung `WEB_FORM`,
   unveränderlicher `urn:gg:public-inquiry:<id>` und deterministischer
   CRM-Vorgangs-ID. Es wird **keine** Nachricht, Termin- oder Zahlaktion
   automatisch ausgelöst. Ein Neustart nach Unterbrechung zwischen den
   Datenbanken kann denselben Pilot ohne doppelten CRM-Fall übernehmen.
6. Der Reverse Proxy muss die tatsächlich geprüfte Client-IP als
   WSGI-`REMOTE_ADDR` bereitstellen und darf nie
   `X-Forwarded-For` aus ungeprüfter Quelle übernehmen. Die lokale
   Rate-Begrenzung beträgt drei neue Anfragen je Client-Adresse und
   UTC-Stunde (nur HMAC-gehashte Stunden-Buckets). Zusätzlich braucht die
   öffentliche Instanz ein Edge-Rate-Limit/WAF, Monitoring sowie
   Postfach- und Betriebsverfügbarkeitstests.

### Aufbewahrung und Datenschutz

Das Postfach speichert Name, Geschäfts-E-Mail und Anfrageinhalt nur für
die manuelle Bearbeitung. **Es ist keine Kontakt- oder Werbedatenbank.**
Die getrennte Datei muss auf einem verschlüsselten Datenträger mit
rollenbegrenztem Zugriff liegen; Zugriff und Backups dürfen personenbezogene
Daten nicht in öffentliche Logs oder Git bringen.

Dabei werden nicht nur E-Mail und Freitext, sondern auch
IP-abgeleitete Ratenprüfsummen und Inhaltsprüfsummen entfernt. Für
abgelehnte oder abgelaufene Anfragen wird ebenfalls der Firmenname
gelöscht. Bereits übernommene CRM-Fälle behalten den im CRM
gespeicherten Firmennamen als getrennte fachliche Quelle.

Ein täglicher, vom Host einzurichtender Aufbewahrungsjob muss
`python -m greengrapeme.cli --db /srv/gg/public-inquiries.sqlite --tenant <echter-mandant> public-inbox-purge --max-age-days 30`
ausführen. Dieser entfernt Kontakt-E-Mail und Freitext nach Ablauf
der Frist. Unerledigte Anfragen werden `EXPIRED`; bereits ins CRM
übernommene Fälle behalten nur minimale Zuordnungsmetadaten.
`ADOPTING`-Fälle sind absichtlich von automatischer Löschung
ausgenommen, bis ein Operator den offenen Übergang sicher aufgelöst hat.
Die konkrete Datenschutzerklärung muss diese Verarbeitung, Empfänger,
Zweck, Rechtsgrundlage und Löschfristen abdecken; Betroffenenanfragen
können zusätzliche Löschmaßnahmen in CRM und Backups erfordern.
Dieser Mechanismus allein **beweist keine DSGVO-Konformität**.

## SEO und maschinenlesbare Inhalte

Jede Landingpage hat einen individuellen deutschen Titel, Meta-Description,
Canonical und Open-Graph-Tags, eine sichtbare H1, eigenständige inhaltliche
Abschnitte, relevante interne Links und klare Kontakt- bzw. Pilotwege.
`GET /sitemap.xml` wird aus den tatsächlichen Routen erzeugt, und
`GET /robots.txt` verweist darauf. Die Sitemap enthält weder
SaaS-Login noch APIs, Platzhalterprofile oder nicht vorhandene Blogbeiträge.

JSON-LD ist serverside in die HTML-Antwort integriert:

- `Organization`: nur der konfigurierte echte Betreiber und Kontakt
- `WebSite` und `WebPage`: konsistente `@id`, Canonical und Beschreibung
- `BreadcrumbList`: tatsächlicher, sichtbarer Seitenpfad
- `SoftwareApplication`: Produkt auf der Startseite; **keine** erfundenen Preise/Reviews
- `Service`: nur die Seite, deren sichtbarer Inhalt einen Software-Service beschreibt
- `FAQPage`: nur bei sichtbaren, identischen Fragen auf `/fragen`

Die öffentlich zugänglichen Seiten halten sich an Googles Leitlinie,
dass strukturierte Daten mit tatsächlich sichtbaren Inhalten
übereinstimmen müssen. Die Struktur ist **keine Garantie für Rich Results**
oder bessere Suchpositionen. Ein Software-App-Rich-Result kann ohne die
erforderlichen verifizierten Preis-/Bewertungsinformationen nicht als
erfolgreich beansprucht werden. Google zeigt FAQ-Rich-Results zudem nur
unter stark eingeschränkten Bedingungen.

GEO/AEO wird hier durch verständliche Fragen, klare Produktgrenzen,
konsistente Begriffe und überprüfbare Fachabschnitte adressiert. Es wird
keine Sichtbarkeit in KI-Antworten garantiert.

## E-E-A-T – belastbare Grundlage, keine Selbstzertifizierung

**Experience:** Aussagekraft der Kunden- und Nutzungsbeispiele erst nach
dokumentierter echter Pilotabnahme veröffentlichen. Keine erfundenen
Testimonials oder Fallstudien.

**Expertise:** Methodik erklärt konkrete Phasen des Vertriebsprozesses,
Prüfung von Quellen, Providerbelegen und Einnahmeabgrenzung.

**Authoritativeness:** Veröffentlichender Betreiber und redaktionelle
Verantwortung müssen verifiziert sichtbar sein; externe
Zertifizierungen/Partnerschaften nicht ohne Nachweise angeben.

**Trust:** Echte Kontakt- und Rechtsangaben, Datenschutzdokumente,
funktionierende Links, keine unrechtmäßigen Kontaktversprechen,
keine irreführenden Verkaufs- oder Umsatzbehauptungen.

Vor Live-Veröffentlichung müssen eine natürliche Person bzw. Organisation
den gesamten Text sachlich prüfen, Legal/Datenschutz freigeben und die
tatsächlichen Angaben eintragen. Alle Provider-/Kosten-/Compliance-Aussagen
sind anhand der realen Bereitstellung zu bestätigen.

## Automatische Checks und manuelle Release-Gates

`python -m unittest tests.test_marketing_site -v` prüft die Routen,
kanonische URLs, einzigartige Titles/Descriptions, JSON-LD-Konsistenz,
Sitemap-/Robots-Konsistenz, interne Links, fehlende Fake-Reviews,
nicht vorhandene Tracker, TLS, fehlende SaaS-Zugriffe und fail-closed
Betreiber-Konfiguration. Die bestehenden SaaS-Browsertests prüfen
`noindex` für Login-Assets.

Ein Marketing-Release benötigt zusätzlich:

1. **Domain und Deploy:** DNS, HTTPS, reale Aufrufbarkeit, korrekter
   Reverse Proxy und funktionierende Impressum-/Datenschutz-Links.
2. **Recht:** Impressum, DSGVO/Informationspflichten, Auftragsverarbeitung,
   tatsächlich eingesetzte Dienstleister und rechtlich geprüfte CTAs.
3. **Fachliche QA:** jede Aussage gegen reale Implementierung und
   Release-Gates prüfen; keine Kundennachweise ohne reale Einwilligung.
4. **Technische SEO-QA:** vollständigen öffentlichen Crawl, Statuscodes,
   Canonicals, Sitemap in Search Console, Rich Results Test,
   Schema Markup Validator sowie mobile Darstellung/Barrierefreiheit prüfen.
5. **Conversion:** Kontaktpostfach und Anfragenbearbeitung end-to-end
   prüfen; erst danach reale Conversion und Kundenfeedback messen.

Das vorhandene Produkt-`release-audit` bleibt unabhängig davon NO-GO,
bis echte Vertriebskanäle, Provider und Betrieb freigegeben sind.
