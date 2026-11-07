"""Public, SEO-readable GreenGrapeMe site. Separate from the OIDC SaaS app.

All factual product claims are bounded by documented domain functionality.
Operator identity and legal URLs are REQUIRED at startup and never invented.
No cookies, embedded trackers, user-generated HTML or untrusted query rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from ipaddress import ip_address
from importlib import resources
from os import environ
from urllib.parse import urlsplit, parse_qs

from .public_inquiries import PublicPilotInbox
import json
import re


_EMAIL = re.compile(r"^[A-Za-z0-9_.+%-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
_PAGE_LIMIT = 200


def _https_url(value: str, *, origin: bool = False) -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= 2048:
        raise ValueError("missing canonical HTTPS configuration")
    if (value != value.strip() or
            any(ord(ch) <= 32 or ord(ch) == 127 for ch in value)):
        raise ValueError("unsafe public URL")
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError:
        raise ValueError("invalid public URL") from None
    if (u.scheme != "https" or not u.hostname or not u.netloc
            or u.username is not None or u.password is not None
            or u.fragment or u.netloc.endswith(":")
            or port == 0 or "%" in u.netloc or "@" in u.netloc
            or "\\" in value):
        raise ValueError("public URL must be canonical HTTPS")
    if origin and (u.path not in ("", "/") or u.query or value.endswith("/")):
        raise ValueError("public site origin must have no path or query")
    return value


@dataclass(frozen=True)
class PublicSiteConfig:
    origin: str
    operator_name: str
    contact_email: str
    imprint_url: str
    privacy_url: str
    app_url: str

    def __post_init__(self):
        _https_url(self.origin, origin=True)
        _https_url(self.imprint_url)
        _https_url(self.privacy_url)
        _https_url(self.app_url)
        if (not isinstance(self.operator_name, str)
                or not 2 <= len(self.operator_name.strip()) <= 160
                or self.operator_name != self.operator_name.strip()
                or any(ord(c) < 32 or c in "<>" for c in self.operator_name)):
            raise ValueError("verified legal operator name required")
        if (not isinstance(self.contact_email, str)
                or len(self.contact_email) > 254
                or not _EMAIL.fullmatch(self.contact_email)):
            raise ValueError("verified public contact email required")


@dataclass(frozen=True)
class Page:
    path: str
    title: str
    description: str
    heading: str
    lead: str
    sections: tuple[tuple[str, tuple[str, ...]], ...]
    related: tuple[str, ...] = ()


# These authored articles are static, specific to GreenGrapeMe and make
# no certifications, independent ROI claims, fake customers or price offers.
_PAGES = (
    Page("/", "KI-gestützte B2B-Vertriebsprozesse",
         "GreenGrapeMe verbindet B2B-Leads, CRM, Vertriebsprozesse und überprüfbare Ergebnisse. Funktionen, Grenzen und Pilotablauf transparent erklärt.",
         "B2B-Vertrieb mit KI strukturieren und nachvollziehen",
         "GreenGrapeMe verbindet Unternehmensrecherche, CRM, Kundenkommunikation, Termine und kommerzielle Nachweise in einer Vertriebsakte. Der produktive Betrieb mit echten Kunden wird noch abgenommen.",
         (
             ("Vom Vertriebsauftrag zum Kundenprozess", (
                 "Der Ausgangspunkt ist ein konkretes Angebot mit Zielgruppe, Region, Preis und verantwortlichen Personen. Unternehmensrecherche und Qualifizierung werden an Quellen gebunden. Im CRM kann daraus eine bearbeitbare Opportunity entstehen. Ein recherchiertes Unternehmen ist dabei ausdrücklich noch keine Kundenanfrage und keine Einwilligung zur Kontaktaufnahme.",
                 "Weitere Schritte betreffen die Bearbeitung tatsächlich eingehender Anfragen, Terminvereinbarungen, Angebote und Vertragsabschlüsse. Bestätigte Zahlungseingänge werden getrennt von gemeldeten Vertriebsereignissen ausgewiesen.",
             )),
             ("Ein Vertriebsprozess statt vieler isolierter Werkzeuge", (
                 "Die Vertriebsakte stellt den Status eines Vorgangs zusammenhängend dar: Herkunft, Kommunikation, Termin, Angebot, Vertrag, Rechnung und Zahlung. Für jeden Schritt ist erkennbar, ob nur eine interne Meldung oder ein unabhängiger Provider-Nachweis vorliegt.",
                 "GreenGrapeMe befindet sich in der Pilot- und Integrationsphase. Es gibt noch keine öffentlich nachgewiesenen Steigerungen von Umsatz, Conversion oder Rentabilität.",
             )),
             ("Für welche Unternehmen der Ansatz gedacht ist", (
                 "Der fachliche Schwerpunkt liegt auf erklärungsbedürftigem B2B-Vertrieb mit dokumentierbarer Zielgruppe, klaren Angebotsbedingungen und menschlicher Verantwortlichkeit. Vor einem Pilot werden Datengrundlage, erlaubte Kommunikationskanäle, Rollen, Messgrößen und externe Systeme gemeinsam abgegrenzt.",
             )),
         ), ("/vertriebsautomatisierung", "/pilotprojekt", "/methodik")),
    Page("/lead-recherche", "Lead-Recherche mit Quellenprüfung",
         "Wie GreenGrapeMe B2B-Unternehmen recherchiert, Quellen verknüpft und Leads ohne erfundene Kontakterlaubnis bewertet.",
         "B2B-Leads recherchieren – mit belegbarer Herkunft",
         "Unternehmensrecherche ist nur der Anfang einer Vertriebskette. GreenGrapeMe unterscheidet auffindbare Unternehmen, qualifizierte Opportunities und tatsächlich kontaktberechtigte Anfragen.",
         (
             ("Rechercheauftrag und Zielgruppenkriterien", (
                 "Ein Rechercheauftrag enthält Angebot, Zielkundensegment und räumliche Eingrenzung. Die vorhandene Discovery-Queue kann neue und bestehende StarFruitMe-Aufträge erfassen. Eine Recherche wird nur ausgeführt, wenn der vertrauenswürdige Host die Datenquelle und ihre Nutzungsrechte freigibt.",
                 "Branchenmerkmale, Unternehmensnamen und Quellennachweise werden nicht allein deshalb als verifiziert betrachtet, weil ein KI-Modell sie plausibel formuliert.",
             )),
             ("Vom Treffer zum CRM-Vorgang", (
                 "Ein gefundener Account kann mit unveränderlicher Quellenreferenz in den CRM-Pilotprozess übernommen werden. Doppelte oder widersprüchliche Zuordnungen sowie vorhandene Kontaktsperren verhindern die Übergabe. Der neue Status ist eine zu prüfende Opportunity, keine fingierte eingegangene Kundenanfrage.",
             )),
             ("Grenzen der Lead-Daten", (
                 "Öffentlich sichtbare Unternehmensdaten erlauben nicht automatisch Werbe-E-Mails oder Anrufe. Eine gesonderte Prüfung der Rechtsgrundlage, des Kanals, des konkreten Empfängers und bestehender Widersprüche bleibt erforderlich. Die technische Identifizierung von Unternehmen ersetzt keine rechtliche Kontaktfreigabe.",
             )),
         ), ("/vertriebsautomatisierung", "/sicherheit", "/pilotprojekt")),
    Page("/vertriebsautomatisierung", "KI-Vertriebsautomatisierung für B2B",
         "Qualifizierung, Antworten, Wiedervorlagen und Vertriebsaufgaben mit GreenGrapeMe. Welche Schritte automatisiert sind und welche Freigaben benötigen.",
         "Vertriebsarbeit automatisieren, ohne Kontrolle zu verlieren",
         "GreenGrapeMe organisiert Vertriebsaktivitäten entlang eines echten CRM-Vorgangs. Externe Nachrichten und andere irreversible Aktionen bleiben an konkrete Berechtigungen und Provider-Nachweise gebunden.",
         (
             ("Qualifizierung und Bearbeitung", (
                 "Im CRM werden eingehende Anfragen und recherchierte Prospects ausdrücklich getrennt. Qualifizierung, Wiedervorlagen und berichtete Gesprächs- oder Angebotsmeilensteine sind nachvollziehbare Vorgänge. Eine Wiedervorlage löst keine automatische Nachricht aus.",
             )),
             ("Kommunikation mit belastbarer Freigabe", (
                 "Für berechtigte Antworten auf bestehende Anfragen ist eine Provideranbindung über PomeloMe und Resend implementiert. Sie verwendet einen dauerhaft gespeicherten Einmalversand-Schutz. Eine HTTP-Annahme durch den Anbieter zählt noch nicht als zugestellte Nachricht; Zustellnachweise werden gesondert abgefragt.",
                 "Allgemeine, unbeaufsichtigte Kaltakquise ist damit weder freigegeben noch als produktiv abgenommen. Die konkrete Rechtsgrundlage und die Empfängeridentität müssen vor jeder Kommunikation geprüft sein.",
             )),
             ("Nächste Aktion statt falscher Autonomie", (
                 "Die Vertriebsakte kann den fachlich nächsten Schritt anzeigen. Solche Hinweise sind keine stillschweigende Autorisierung zum Senden, Buchen, Signieren oder Abbuchen. Dieser Unterschied schützt Kunden und verhindert, dass eine überzeugende KI-Antwort als bewiesenes Geschäftsergebnis ausgegeben wird.",
             )),
         ), ("/crm-vertriebsakte", "/termine-vertraege", "/sicherheit")),
    Page("/crm-vertriebsakte", "CRM-Vertriebsakte und Sales Pipeline",
         "Eine Vertriebsakte zeigt Lead-Quelle, Gesprächsstatus, Buchung, Angebot, Vertrag, Rechnungsstand und bestätigte Zahlungen.",
         "Eine Vertriebsakte für die gesamte B2B-Kundenreise",
         "Statt isolierter Kontaktlisten zeigt GreenGrapeMe, wo ein Vorgang steht, welche Belege existieren und welche Arbeit fachlich als Nächstes erforderlich ist.",
         (
             ("Einheitlicher Vorgangsverlauf", (
                 "Die geschützte CRM-Ansicht liest den Zustand direkt aus den bestehenden Vertriebsregistern. Sie verknüpft Lead-Ursprung, Kommunikation, Kalender, Vertrag, Rechnungen und Bankbelege für denselben Mandanten und denselben CRM-Vorgang.",
                 "Die Darstellung speichert keine zweite Kopie der Kundendaten. Aktuelle Mandantenberechtigungen werden für jede API-Anfrage erneut geprüft.",
             )),
             ("Gemeldete und bestätigte Meilensteine", (
                 "Ein als durchgeführt gemeldeter Termin ist nicht automatisch ein bestätigtes Gespräch. Ein signierter Vertrag bedeutet noch keinen Zahlungseingang. Die Ansicht kennzeichnet deshalb interne Meldungen, Providerbestätigungen und offene Prüfungen getrennt.",
             )),
             ("Vertriebssteuerung mit Einschränkungen", (
                 "Bestätigte Kundenzahlungen, offene Forderungen und zu klärende Erstattungen werden getrennt dargestellt. Die Beträge sind weder automatisch Plattformumsatz noch ein Beleg für den kausal durch GreenGrapeMe erzeugten Mehrumsatz. Für eine belastbare Erfolgsbewertung braucht es zusätzliche Kosten- und Vergleichsdaten.",
             )),
         ), ("/umsatznachweise", "/pilotprojekt", "/methodik")),
    Page("/termine-vertraege", "Terminvereinbarung und Vertragsprozess",
         "Wie GreenGrapeMe B2B-Termine, Angebotsfreigaben und unterschriebene Verträge mit getrennten Nachweisstufen verarbeitet.",
         "Termine und Verträge nachvollziehbar bearbeiten",
         "Die Vertriebsstrecke unterscheidet zwischen einer Terminabsicht, einer beim Kalenderanbieter bestätigten Buchung und einem tatsächlich stattgefundenen Gespräch.",
         (
             ("Kalender und Buchungsstatus", (
                 "Terminabsichten können im CRM erfasst werden. Die Kalenderintegration kann bestätigte Buchungen und Stornierungen anhand unabhängiger Providerinformationen übernehmen. Bei mehrdeutigen Ergebnissen wird nicht einfach ein zweiter Termin erzeugt.",
                 "Ein bestätigter Kalendereintrag ist kein Teilnahmebeleg. Absagen, Nichterscheinen und eine nachträgliche Gesprächsbewertung bleiben separate fachliche Schritte.",
             )),
             ("Angebote und Freigaben", (
                 "Der Vertragsteil bindet ein Angebot an den vorhandenen CRM-Vorgang und eingefrorene Pilotkonditionen. Eine fachlich freigegebene Angebotsversion wird von einer tatsächlich extern bestätigten Signatur unterschieden. KI-generierte Inhalte erhalten dadurch keine eigenständige Zeichnungsbefugnis.",
             )),
             ("Was noch live geprüft werden muss", (
                 "Die interne Fachlogik wurde mit abgefangenen Providerantworten Ende-zu-Ende getestet. Eine vollständige Abnahme echter Kundenkalender, Einladungen, Signaturprozesse und aller Fehlerfälle steht für einen produktiven Pilot noch aus. Eine lokale Testbestätigung ist keine Produktivfreigabe.",
             )),
         ), ("/crm-vertriebsakte", "/umsatznachweise", "/pilotprojekt")),
    Page("/umsatznachweise", "Vertriebskennzahlen und Umsatznachweise",
         "GreenGrapeMe trennt Leads, gemeldete Erfolge, unterschriebene Verträge, Rechnungen und unabhängig bestätigte Kundenzahlungen.",
         "Vertriebserfolge messen, ohne Umsatz zu erfinden",
         "Ein gewonnener Lead, ein vereinbarter Termin und eine ausgestellte Rechnung sind unterschiedliche Ereignisse. GreenGrapeMe führt sie als getrennte Nachweisstufen.",
         (
             ("Was als Einnahme zählt", (
                 "Kundenzahlungen werden erst nach unabhängig bestätigter Bank- oder Providerbewegung berücksichtigt. Erstattungen reduzieren den bestätigten Nettozahlungseingang. Rechnungen und Verträge bleiben eigene Nachweiskategorien und werden nicht voreilig als vereinnahmtes Geld gezählt.",
             )),
             ("Forderungen und Klärfälle", (
                 "Die Vertriebsakte kann bestätigte Rechnungsbeträge, Gutschriften, offene Forderungen und Rückerstattungsbedarf darstellen. Wiederholte oder widersprüchliche Zahlungsbelege werden durch die bestehenden Transaktions- und Belegprüfungen begrenzt.",
             )),
             ("Welche Kennzahlen damit nicht bewiesen sind", (
                 "Ein Kundenzahlungseingang ist nicht automatisch GreenGrapeMe-Umsatz. Ohne Vergleichsgruppe, vollständig erfasste Kosten und nachweisbare Ausgangssituation lässt sich weder ein kausaler Vertriebszuwachs noch die Profitabilität behaupten. Solche Nachweise sind Bestandteil einer späteren kommerziellen Pilotbewertung.",
             )),
         ), ("/methodik", "/pilotprojekt", "/crm-vertriebsakte")),
    Page("/methodik", "Methodik und Nachweisgrenzen",
         "Offene Methodik: Datenquellen, Einwilligung, Testnachweise, KI-Grenzen und noch nicht abgeschlossene GreenGrapeMe-Live-Abnahme.",
         "So werden GreenGrapeMe-Aussagen überprüft",
         "Unsere Produktdokumentation trennt implementierte Fachlogik, lokale Tests und bestätigte Vorgänge bei echten externen Anbietern. Diese Trennung ist die Grundlage unserer veröffentlichten Funktionsaussagen.",
         (
             ("Was sich technisch nachvollziehen lässt", (
                 "Für CRM-Vorgänge, Kalenderbuchungen, Signaturen, Rechnungen und Zahlungen existieren unterschiedliche Zustände und Belegreferenzen. Die Codebasis enthält Integrationstests über die gesamte lokale Vertriebskette. Dort werden echte Domänenmodule mit abgefangenen Providerantworten geprüft.",
                 "Ein erfolgreicher Test mit einem Provider-Double belegt die interne Verarbeitung, nicht die tatsächliche Erreichbarkeit oder rechtliche Zulässigkeit einer produktiven Providertransaktion.",
             )),
             ("Wie mit Unsicherheit umgegangen wird", (
                 "Bei unklaren Versand- oder Zahlungsresultaten darf GreenGrapeMe keinen Erfolg erfinden. Unbekannte Zustände bleiben prüfpflichtig. Rechercheergebnisse und generierte Texte müssen an Quellen gebunden bleiben und dürfen weder Identitäten noch Kontakterlaubnisse fingieren.",
             )),
             ("Verantwortung und Produktstand", (
                 "Der rechtlich verantwortliche Betreiber und der erreichbare Kontakt sind auf der Kontaktseite ausgewiesen. Technische Änderungen werden im Quellrepository dokumentiert. Vor einer öffentlichen Erfolgs- oder Compliance-Behauptung sind die jeweiligen Nachweise gesondert zu prüfen.",
                 "GreenGrapeMe ist derzeit nicht als vollständig produktionsreife autonome Vertriebsgesellschaft freigegeben. Es liegen keine hier veröffentlichten verifizierten Kundenreferenzen oder Renditeversprechen vor.",
             )),
         ), ("/sicherheit", "/ueber-uns", "/pilotprojekt")),
    Page("/sicherheit", "Sicherheit, Datenschutz und Grenzen",
         "Mandantenberechtigungen, OIDC-Anmeldung, externe Effektkontrollen, Datenschutzgrenzen und offene Sicherheitsabnahmen bei GreenGrapeMe.",
         "Sicherheit und Datenschutz im Vertriebsprozess",
         "GreenGrapeMe verarbeitet potenziell sensible B2B-Kunden- und Geschäftsvorgänge. Die technische Architektur setzt deshalb auf aktuelle Zugriffsberechtigungen, Quellennachweise und begrenzte externe Aktionen.",
         (
             ("Zugang und Mandantentrennung", (
                 "Die geschützte SaaS-Anwendung verwendet eine OIDC-Anmeldung und prüft Mandantenmitgliedschaften serverseitig. API-Eingaben werden validiert. Die öffentliche Marketing-Website lädt keine fremden Tracker und benötigt keine Anmeldung.",
             )),
             ("Externe Aktionen und Wiederanlauf", (
                 "Kommunikations- und Kalenderaktionen sind durch dauerhafte Effektregister und Zustandsprüfungen begrenzt. Bei mehrdeutigen Providerantworten wird eine Nachricht nicht blind erneut gesendet. Zahlungs- und Vertragsbelege werden gegen die zugehörigen Vorgänge und ihre ursprünglichen Quellen geprüft.",
             )),
             ("Datenschutz und ausstehende Abnahme", (
                 "Diese Sicherheitsmechanismen sind keine Zertifizierung und kein pauschaler DSGVO-Konformitätsnachweis. Für einen produktiven Einsatz sind insbesondere Rechtsgrundlagen, Informationspflichten, Auftragsverarbeitung, Löschfristen, eingesetzte Dienstleister, Hosting, Penetrationstests und Wiederherstellung anhand der konkreten Installation zu prüfen.",
                 "Rechtlich verbindliche Angaben des Betreibers und die Datenschutzhinweise sind über die Links im Seitenfuß erreichbar. Es werden keine nicht vorhandenen Sicherheitszertifikate oder Audits behauptet.",
             )),
         ), ("/methodik", "/kontakt", "/pilotprojekt")),
    Page("/pilotprojekt", "B2B-Vertriebspilot anfragen",
         "So lässt sich GreenGrapeMe mit einem begrenzten B2B-Vertriebsauftrag testen: Zielgruppe, erlaubte Kanäle, Nachweise und klare Abnahmekriterien.",
         "GreenGrapeMe in einem begrenzten B2B-Piloten prüfen",
         "Ein Pilotprojekt soll zuerst beweisen, dass sich ein konkret definierter Vertriebsauftrag nachvollziehbar bearbeiten lässt. Derzeit wird kein ungeprüfter vollautonomer Produktivbetrieb zugesagt.",
         (
             ("1. Vertriebsauftrag definieren", (
                 "Ausgangspunkt sind Produkt oder Dienstleistung, Zielkundengruppe, regionaler Markt, Angebot, Verantwortliche und messbare Ziele. Vor der Recherche werden Quellenrechte und zulässige Kontaktkanäle geprüft.",
             )),
             ("2. Prozess und Systemgrenzen festlegen", (
                 "Der Pilot legt fest, welche CRM-, Kalender-, Signatur- und Zahlungsanbieter tatsächlich verbunden sind. Es wird dokumentiert, welche Schritte intern verarbeitet werden können, welche menschliche Freigaben benötigen und welche externen Provider noch nicht produktiv abgenommen sind.",
             )),
             ("3. Ergebnisse transparent bewerten", (
                 "Ausgewertet werden unter anderem passende Accounts, qualifizierte Vorgänge, bestätigte Termine, Vertragsnachweise, Zahlungseingänge, Kosten und Klärfälle. Einmalige Zahlungen und gemeldete Erfolge werden nicht automatisch in wiederkehrenden Umsatz umgerechnet.",
                 "Eine verbindliche Preisangabe oder garantierte Umsatzsteigerung wird auf dieser Website nicht behauptet. Umfang, Verfügbarkeit und kaufmännische Bedingungen müssen für den konkreten Pilot separat vereinbart werden.",
             )),
         ), ("/kontakt", "/sicherheit", "/umsatznachweise")),
    Page("/ueber-uns", "Über das Produkt und Verantwortlichkeit",
         "Wer GreenGrapeMe veröffentlicht, welches Produktversprechen gilt und warum Funktions- und Umsatzbehauptungen überprüfbar sein müssen.",
         "GreenGrapeMe: Produkt, Verantwortlichkeit und Anspruch",
         "GreenGrapeMe ist eine in Entwicklung befindliche Software für nachvollziehbare B2B-Vertriebsprozesse. Nicht das Nachrichtenvolumen, sondern dokumentierbare Kundenarbeit ist der fachliche Maßstab.",
         (
             ("Produktfokus", (
                 "Die Software verbindet vorhandene FruitStack-Funktionen mit einem Vertriebsprozess aus Unternehmensrecherche, CRM, Kommunikation, Terminplanung und kommerziellen Belegen. Der geschützte Arbeitsbereich und die öffentliche Informationswebsite erfüllen unterschiedliche Aufgaben.",
             )),
             ("Redaktionelle Grundsätze", (
                 "Auf diesen Seiten werden keine Kundenrezensionen, Awards, Partnerzertifizierungen oder Leistungswerte erfunden. Wo nur Offline-Tests vorliegen, wird dies ausdrücklich benannt. Änderungen an Produktversprechen sollen erst nach nachvollziehbarer Prüfung der jeweiligen Funktion veröffentlicht werden.",
             )),
             ("Wer verantwortlich ist", (
                 "Die rechtlich verantwortliche Organisation und der direkte Kontakt sind im Seitenfuß und auf der Kontaktseite angegeben. Die verlinkten rechtlichen Angaben müssen vor einer öffentlichen Bereitstellung verifiziert und auf den tatsächlichen Betreiber abgestimmt werden.",
             )),
         ), ("/methodik", "/kontakt", "/sicherheit")),
    Page("/kontakt", "Kontakt und verantwortlicher Betreiber",
         "Kontaktieren Sie den verantwortlichen Betreiber von GreenGrapeMe für Produktfragen, Pilotprojekte und rechtliche Anfragen.",
         "Kontakt für Produktfragen und Pilotprojekte",
         "Fragen zu GreenGrapeMe, zu einem begrenzten Vertriebsauftrag oder zur Verarbeitung Ihrer Daten können an den im Folgenden ausgewiesenen Betreiber gerichtet werden.",
         (
             ("Anfragen zum Piloteinsatz", (
                 "Nennen Sie für einen ersten Austausch das vertriebene Angebot, die Zielgruppe, die vorgesehenen Regionen und vorhandene CRM- oder Kommunikationssysteme. Für echte Nachrichten und Transaktionen werden die Berechtigungen und Provideranbindungen vor dem Einsatz gesondert geprüft.",
                 "Bitte senden Sie keine Zugangsdaten, vollständigen Kundendatensätze oder anderen sensiblen Informationen per unverschlüsselter E-Mail.",
             )),
         ), ("/pilotprojekt", "/ueber-uns", "/sicherheit")),
    Page("/fragen", "Fragen zur KI-Vertriebssoftware",
         "Antworten zu B2B-Lead-Recherche, Kontaktberechtigungen, Terminen, Preisen, Datensicherheit und dem GreenGrapeMe-Pilotstatus.",
         "Häufige Fragen zu GreenGrapeMe",
         "Die Antworten beschreiben den aktuellen fachlichen und technischen Umfang, nicht eine garantierte Live-Verfügbarkeit oder Umsatzsteigerung.",
         (), ("/pilotprojekt", "/methodik", "/kontakt")),
)
PAGES = {page.path: page for page in _PAGES}

FAQ = (
    ("Schreibt GreenGrapeMe automatisch recherchierte Firmen an?",
     "Nein. Ein Recherchetreffer ist keine Einwilligung oder Kontaktfreigabe. Jede externe Kontaktaufnahme benötigt eine gesondert geprüfte Rechtsgrundlage und den erlaubten Kommunikationskanal."),
    ("Ist eine gebuchte Besprechung ein bestätigter Verkauf?",
     "Nein. Kalenderbuchung, tatsächliche Teilnahme, unterschriebener Vertrag und Zahlungseingang sind verschiedene Nachweisstufen."),
    ("Kann GreenGrapeMe Kundenzahlungen automatisch als Umsatz ausweisen?",
     "Eine unabhängig bestätigte Bankzahlung wird als Kundengeldeingang verbucht. Daraus folgt weder automatisch Plattformumsatz noch kausal durch die Software erzeugter Mehrumsatz."),
    ("Ist GreenGrapeMe bereits vollständig produktionsreif?",
     "Nein. Die interne Fachlogik ist umfangreich getestet, aber echte Providerintegration, Betriebssicherheit und rechtliche Freigaben müssen anhand eines konkreten produktiven Piloten abgenommen werden."),
    ("Welche Daten benötigt ein Pilotprojekt?",
     "Ein Pilot benötigt ein definiertes B2B-Angebot, eine Zielgruppe, rechtmäßig nutzbare Recherchequellen, vereinbarte Kommunikationskanäle und klare Verantwortlichkeiten. Externe Systeme werden separat geprüft."),
    ("Gibt es veröffentlichte garantierte Preise oder Umsatzzuwächse?",
     "Nein. Umfang, kaufmännische Bedingungen und Verfügbarkeit eines Piloten werden individuell vereinbart; garantierte Umsatzsteigerungen werden nicht behauptet."),
)


def _canonical(config: PublicSiteConfig, path: str) -> str:
    return config.origin + (path if path != "/" else "/")


def _structured(config: PublicSiteConfig, page: Page) -> dict:
    canonical = _canonical(config, page.path)
    org_id = config.origin + "/#organisation"
    website_id = config.origin + "/#website"
    graph = [
        {
            "@type":"Organization", "@id":org_id,
            "name":config.operator_name, "url":config.origin+"/",
            "email":config.contact_email,
        },
        {
            "@type":"WebSite", "@id":website_id,
            "url":config.origin+"/", "name":"GreenGrapeMe",
            "inLanguage":"de-DE", "publisher":{"@id":org_id},
        },
        {
            "@type":"WebPage", "@id":canonical+"#webpage",
            "url":canonical, "name":page.title,
            "description":page.description,
            "inLanguage":"de-DE",
            "isPartOf":{"@id":website_id}, "publisher":{"@id":org_id},
        },
    ]
    if page.path != "/":
        graph.append({
            "@type":"BreadcrumbList",
            "itemListElement":[
                {"@type":"ListItem","position":1,
                 "name":"Startseite","item":config.origin+"/"},
                {"@type":"ListItem","position":2,
                 "name":page.heading,"item":canonical},
            ]
        })
    if page.path == "/":
        graph.append({
            "@type":"SoftwareApplication", "@id":config.origin+"/#software",
            "name":"GreenGrapeMe", "url":config.app_url,
            "applicationCategory":"BusinessApplication",
            "operatingSystem":"Web",
            "description":page.description,
            "publisher":{"@id":org_id},
        })
    if page.path == "/vertriebsautomatisierung":
        graph.append({
            "@type":"Service", "name":page.heading,
            "serviceType":"Softwaregestützte B2B-Vertriebsprozesse",
            "description":page.description,
            "provider":{"@id":org_id},
            "url":canonical,
        })
    if page.path == "/fragen":
        graph.append({
            "@type":"FAQPage",
            "mainEntity":[{"@type":"Question","name":question,
                           "acceptedAnswer":{"@type":"Answer","text":answer}}
                          for question,answer in FAQ],
        })
    return {"@context":"https://schema.org","@graph":graph}


def _json_ld(document: dict) -> str:
    # HTML script-data termination is dangerous even for application/ld+json.
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).replace("<","\\u003c").replace(">", "\\u003e").replace("&","\\u0026")


def _pilot_form(config: PublicSiteConfig, inbox: PublicPilotInbox) -> str:
    e=lambda value:escape(value,quote=True)
    return (
        '<section class="marketing-section"><h2>Unverbindliche Pilotanfrage</h2>'
        '<p>Beschreiben Sie Ihren konkreten B2B-Vertriebsauftrag. '
        'Die Anfrage wird zur manuellen Prüfung gespeichert. '
        'Es erfolgt keine automatische Kontaktaufnahme oder CRM-Qualifizierung.</p>'
        '<form id="pilot-inquiry-form" action="/pilot-anfrage" method="post" '
        'accept-charset="UTF-8">'
        '<input type="hidden" name="form_token" value="'+e(inbox.issue_token())+'">'
        '<div><label for="inquiry-company">Unternehmen</label>'
        '<input id="inquiry-company" name="unternehmen" required maxlength="160" '
        'autocomplete="organization"></div>'
        '<div><label for="inquiry-email">Geschäftliche Kontakt-E-Mail</label>'
        '<input id="inquiry-email" type="email" name="email" required '
        'maxlength="254" autocomplete="email"></div>'
        '<div><label for="inquiry-message">Vertriebsziel und Zielgruppe</label>'
        '<textarea id="inquiry-message" name="anliegen" rows="5" '
        'maxlength="800" required></textarea></div>'
        '<div class="marketing-honeypot" aria-hidden="true">'
        '<label for="inquiry-website">Bitte nicht ausfüllen</label>'
        '<input id="inquiry-website" name="website" tabindex="-1" '
        'autocomplete="off"></div>'
        '<label><input type="checkbox" name="datenschutz" value="on" required>'
        ' Ich habe die <a href="'+e(config.privacy_url)+'">Datenschutzhinweise</a> '
        'zur Bearbeitung meiner Anfrage gelesen. '
        'Dies ist keine Einwilligung in Werbung.</label>'
        '<p>Keine Zugangsdaten oder personenbezogenen Kundendatensätze eintragen. '
        'Nicht bearbeitete Anfragen werden nach der festgelegten Frist bereinigt.</p>'
        '<button type="submit">Pilotanfrage zur Prüfung einreichen</button>'
        '</form></section>'
    )


def _html(config: PublicSiteConfig, page: Page,
          inbox: PublicPilotInbox | None = None) -> bytes:
    canonical = _canonical(config, page.path)
    e = lambda value: escape(value, quote=True)
    nav = (
        ("/","Start"),
        ("/lead-recherche","Lead-Recherche"),
        ("/vertriebsautomatisierung","Automatisierung"),
        ("/crm-vertriebsakte","CRM"),
        ("/pilotprojekt","Pilotprojekt"),
        ("/methodik","Methodik"),
        ("/kontakt","Kontakt"),
    )
    links = " ".join(
        f'<a href="{e(path)}"'+(' aria-current="page"' if page.path==path else "")+
        f'>{e(label)}</a>' for path,label in nav
    )
    sections = "".join(
        '<section class="marketing-section"><h2>'+e(title)+'</h2>'+
        "".join("<p>"+e(paragraph)+"</p>" for paragraph in paragraphs)+
        "</section>" for title,paragraphs in page.sections
    )
    if page.path == "/fragen":
        sections += "".join(
            '<section class="marketing-section"><h2>'+e(question)+'</h2>'+
            '<p>'+e(answer)+'</p></section>' for question,answer in FAQ
        )
    if page.path == "/kontakt":
        sections += (
            '<section class="marketing-section"><h2>Verantwortlicher Betreiber</h2>'+
            '<p>'+e(config.operator_name)+'</p>'+
            '<p>E-Mail: <a href="mailto:'+e(config.contact_email)+'">'+
            e(config.contact_email)+'</a></p></section>'
        )
    if page.path == "/pilotprojekt" and inbox is not None:
        sections += _pilot_form(config,inbox)
    related = "".join(
        f'<li><a href="{e(path)}">{e(PAGES[path].heading)}</a></li>'
        for path in page.related
    )
    head = (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'+
        '<meta name="viewport" content="width=device-width,initial-scale=1">'+
        '<meta name="color-scheme" content="dark">'+
        '<title>'+e(page.title)+' | GreenGrapeMe</title>'+
        '<meta name="description" content="'+e(page.description)+'">'+
        '<meta name="robots" content="index,follow,max-snippet:-1">'+
        '<link rel="canonical" href="'+e(canonical)+'">'+
        '<link rel="alternate" hreflang="de-DE" href="'+e(canonical)+'">'+
        '<meta property="og:type" content="website">'+
        '<meta property="og:locale" content="de_DE">'+
        '<meta property="og:site_name" content="GreenGrapeMe">'+
        '<meta property="og:title" content="'+e(page.title)+'">'+
        '<meta property="og:description" content="'+e(page.description)+'">'+
        '<meta property="og:url" content="'+e(canonical)+'">'+
        '<link rel="stylesheet" href="/app.css">'+
        '<link rel="stylesheet" href="/marketing.css">'+
        '<script type="application/ld+json">'+_json_ld(_structured(config,page))+
        '</script></head>'
    )
    document = (
        head+'<body class="marketing-body">'+
        '<a class="marketing-skip" href="#inhalt">Zum Inhalt springen</a>'+
        '<header class="marketing-header"><strong><a href="/">GreenGrapeMe</a></strong>'+
        '<nav aria-label="Hauptnavigation">'+links+'</nav></header>'+
        '<main id="inhalt"><article class="marketing-article">'+
        '<p class="marketing-eyebrow">GreenGrapeMe · B2B-Vertriebssoftware · Pilotphase</p>'+
        '<h1>'+e(page.heading)+'</h1>'+
        '<p class="marketing-lead">'+e(page.lead)+'</p>'+
        sections+
        '<section class="marketing-next"><h2>Nächster Schritt</h2>'+
        '<p>Ein begrenzter Pilot klärt Anforderungen, externe Freigaben und die überprüfbaren Erfolgskriterien.</p>'+
        '<a href="/pilotprojekt">Pilotablauf ansehen</a> · '+
        '<a href="/pilotprojekt">Pilotprojekt anfragen</a></section>'+
        (('<aside class="marketing-related"><h2>Weiterführende Informationen</h2><ul>'+
          related+'</ul></aside>') if related else "")+
        '</article></main>'+
        '<footer class="marketing-footer"><p>GreenGrapeMe · Verantwortlicher Betreiber: '+
        e(config.operator_name)+'</p><nav aria-label="Rechtliche und redaktionelle Informationen">'+
        '<a href="'+e(config.imprint_url)+'">Impressum</a> · '+
        '<a href="'+e(config.privacy_url)+'">Datenschutz</a> · '+
        '<a href="/ueber-uns">Über uns</a> · <a href="/methodik">Methodik</a> · '+
        '<a href="/fragen">Fragen</a> · '+
        '<a href="'+e(config.app_url)+'">Zur geschützten Anwendung</a>'+
        '</nav><p>Keine Garantie für Umsatzsteigerung, Produktivverfügbarkeit oder Datenschutz-Zertifizierung.</p>'+
        '</footer></body></html>'
    )
    return document.encode("utf-8")


def _response(start_response, status: str, payload: bytes, mimetype: str,
              *, indexable: bool = False, head: bool = False,
              private: bool = False, forms: bool = False,
              location: str | None = None):
    headers = [
        ("Content-Type",mimetype),
        ("Content-Length",str(len(payload))),
        ("Cache-Control","no-store, max-age=0" if private else
         "public, max-age=300" if indexable else "public, max-age=3600"),
        ("Strict-Transport-Security","max-age=31536000"),
        ("X-Content-Type-Options","nosniff"),
        ("X-Frame-Options","DENY"),
        ("Referrer-Policy","strict-origin-when-cross-origin"),
        ("Content-Security-Policy",
         "default-src 'none'; style-src 'self'; script-src 'none'; "
         "img-src 'self'; base-uri 'none'; form-action "+
         ("'self'" if forms else "'none'")+"; "
         "frame-ancestors 'none'; connect-src 'none'"),
        ("Content-Language","de-DE"),
    ]
    if not indexable:
        headers.append(("X-Robots-Tag","noindex, nofollow"))
    if location is not None:
        headers.append(("Location",location))
    start_response(status,headers)
    return [] if head else [payload]


def create_marketing_app(config: PublicSiteConfig, *,
                         inbox: PublicPilotInbox | None = None):
    """Standalone public WSGI app: deploy at GG_PUBLIC_ORIGIN, NOT SaaS origin."""
    if not isinstance(config,PublicSiteConfig):
        raise ValueError("verified public site configuration required")
    if inbox is not None and not isinstance(inbox,PublicPilotInbox):
        raise ValueError("verified separate public inquiry inbox required")

    def app(environ,start_response):
        if environ.get("wsgi.url_scheme") != "https":
            return _response(start_response,"403 Forbidden",b"TLS required",
                             "text/plain; charset=utf-8")
        method = environ.get("REQUEST_METHOD")
        path = environ.get("PATH_INFO","")
        if path == "/pilot-anfrage" and method == "POST" and inbox is not None:
            # Same-origin HTML form only. No cookies, CORS or access to SaaS.
            if (environ.get("HTTP_ORIGIN") != config.origin or
                    environ.get("HTTP_SEC_FETCH_SITE","same-origin")
                        not in ("same-origin","none")):
                return _response(start_response,"403 Forbidden",b"Origin denied",
                                 "text/plain; charset=utf-8",private=True)
            mime=environ.get("CONTENT_TYPE","").split(";")[0].strip().lower()
            size=environ.get("CONTENT_LENGTH","")
            if (mime!="application/x-www-form-urlencoded" or
                    not isinstance(size,str) or not size.isdecimal()
                    or len(size)>5 or not 1<=int(size)<=3000):
                return _response(start_response,"400 Bad Request",b"Invalid form",
                                 "text/plain; charset=utf-8",private=True)
            try:
                raw=environ["wsgi.input"].read(int(size))
                if not isinstance(raw,bytes) or len(raw)!=int(size):
                    raise ValueError("incomplete form")
                values=parse_qs(raw.decode("utf-8"),keep_blank_values=True,
                    strict_parsing=True,encoding="utf-8",errors="strict",
                    max_num_fields=8)
                allowed={"form_token","unternehmen","email","anliegen",
                         "datenschutz","website"}
                if set(values)!=allowed or any(len(v)!=1 for v in values.values()):
                    raise ValueError("ambiguous form")
                # Local Nginx overwrites X-Real-IP with its socket
                # peer. Trust it ONLY when the direct WSGI peer is loopback;
                # never use unsanitized X-Forwarded-For from the internet.
                peer=environ.get("REMOTE_ADDR","")
                effective_peer=peer
                if peer in ("127.0.0.1","::1"):
                    real=environ.get("HTTP_X_REAL_IP")
                    if real is not None:
                        if not isinstance(real,str) or len(real)>45:
                            raise ValueError("invalid reverse proxy client IP")
                        try:
                            effective_peer=str(ip_address(real))
                        except ValueError:
                            raise ValueError("invalid reverse proxy client IP") from None
                inbox.submit(
                    token=values["form_token"][0],
                    company_name=values["unternehmen"][0],
                    contact_email=values["email"][0],
                    message=values["anliegen"][0],
                    privacy_ack=values["datenschutz"][0],
                    honeypot=values["website"][0],
                    remote_addr=effective_peer)
            except PermissionError:
                return _response(start_response,"429 Too Many Requests",
                                 b"Please retry later",
                                 "text/plain; charset=utf-8",private=True)
            except (ValueError,UnicodeError,OverflowError):
                return _response(start_response,"400 Bad Request",b"Invalid form",
                                 "text/plain; charset=utf-8",private=True)
            return _response(start_response,"303 See Other",b"",
                             "text/plain; charset=utf-8",private=True,
                             location="/anfrage-erhalten")
        if method not in ("GET","HEAD"):
            return _response(start_response,"405 Method Not Allowed",
                             b"Method not allowed","text/plain; charset=utf-8")

        if not isinstance(path,str) or len(path)>_PAGE_LIMIT:
            return _response(start_response,"404 Not Found",b"Not found",
                             "text/plain; charset=utf-8",head=method=="HEAD")
        if path == "/anfrage-erhalten" and inbox is not None:
            payload=(
                '<!doctype html><html lang="de"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<meta name="robots" content="noindex,nofollow">'
                '<title>Pilotanfrage eingegangen | GreenGrapeMe</title>'
                '<link rel="stylesheet" href="/app.css">'
                '<link rel="stylesheet" href="/marketing.css"></head>'
                '<body class="marketing-body"><main><h1>Anfrage zur Prüfung eingegangen</h1>'
                '<p>Die Übermittlung wurde angenommen. Es wurde noch kein '
                'Vertriebsauftrag gestartet und keine Kontaktfreigabe erteilt.</p>'
                '<a href="/">Zur Startseite</a></main></body></html>'
            ).encode("utf-8")
            return _response(start_response,"200 OK",payload,
                             "text/html; charset=utf-8",
                             private=True,head=method=="HEAD")
        if path in PAGES:
            form_enabled=path=="/pilotprojekt" and inbox is not None
            return _response(
                start_response,"200 OK",_html(config,PAGES[path],inbox),
                "text/html; charset=utf-8",indexable=True,
                private=form_enabled,forms=form_enabled,head=method=="HEAD")
        if path in ("/marketing.css","/app.css"):
            filename = "marketing.css" if path=="/marketing.css" else "app.css"
            content = (resources.files("greengrapeme") / "web" / filename).read_bytes()
            return _response(start_response,"200 OK",content,
                             "text/css; charset=utf-8",head=method=="HEAD")
        if path == "/sitemap.xml":
            urls = "".join(
                "<url><loc>"+escape(_canonical(config,page.path))+"</loc></url>"
                for page in _PAGES)
            payload = ('<?xml version="1.0" encoding="UTF-8"?>'+
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+
                       urls+"</urlset>").encode("utf-8")
            return _response(start_response,"200 OK",payload,
                             "application/xml; charset=utf-8",head=method=="HEAD")
        if path == "/robots.txt":
            payload = ("User-agent: *\nAllow: /\nDisallow: /api/\n"+
                       "Sitemap: "+config.origin+"/sitemap.xml\n").encode("utf-8")
            return _response(start_response,"200 OK",payload,
                             "text/plain; charset=utf-8",head=method=="HEAD")
        return _response(start_response,"404 Not Found",b"Not found",
                         "text/plain; charset=utf-8",head=method=="HEAD")
    return app


def create_marketing_service_from_env():
    """Gunicorn factory; legally responsible identity must be supplied."""
    keys = {
        "origin":"GG_PUBLIC_ORIGIN",
        "operator_name":"GG_PUBLIC_OPERATOR_NAME",
        "contact_email":"GG_PUBLIC_CONTACT_EMAIL",
        "imprint_url":"GG_PUBLIC_IMPRINT_URL",
        "privacy_url":"GG_PUBLIC_PRIVACY_URL",
        "app_url":"GG_PUBLIC_APP_URL",
    }
    # Public web process only holds access to its own narrow PII inbox.
    # The SaaS business database and OIDC credentials never enter this host.
    inbox=PublicPilotInbox(
        environ["GG_PUBLIC_INBOX_DB"],
        tenant=environ["GG_PUBLIC_INQUIRY_TENANT"],
        signing_key=environ["GG_PUBLIC_FORM_KEY"])
    return create_marketing_app(PublicSiteConfig(
        **{key:environ[name] for key,name in keys.items()}),inbox=inbox)
