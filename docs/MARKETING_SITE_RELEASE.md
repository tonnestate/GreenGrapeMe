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
