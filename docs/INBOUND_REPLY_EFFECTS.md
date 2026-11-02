# GreenGrapeMe – kontrollierter Reply-Effekt über PomeloMe (P0, 02.11.2026)

## Umfang

Die neue GreenGrapeMe-Schnittstelle `ReplyEffects` bindet **Antworten auf vorhandene, nachgewiesene eingehende Geschäftsanfragen** an die bereits bestehende FruitStack-Ausführungsschicht **PomeloMe EffectGateway**. Es gibt **keine** zweite Versandengine, kein eigenes Mailserver-/Telefonie-Backend und keine frei auslösbare Massenansprache. Die vorhandene `PilotSalesFlow`-Opportunity und Pilot-ID bleiben der geschäftliche Kontext.

**Der Code integriert den realen PomeloMe-Vertrag:** `EffectIntent(run_id,effect_id,tool,effect_class,args,required_capabilities,idempotency_key)`, `AuthorityEnvelope`, `EffectClass.IRREVERSIBLE` und `EffectGateway.execute(intent,authority)`. Die externe Wirkung erfolgt ausschließlich über einen vom authentifizierten FruitStack-Host bereitgestellten Adapter unter dem präzisen Toolnamen `greengrapeme.send_authorized_reply`. Dieser Adapter ist **noch nicht implementiert oder als Provider installiert**. Der Code führt auf einem korrekt konfigurierten Host eine echte Gateway-Ausführung aus; Offline-Tests verwenden Testdoubles und **beweisen keinen versendeten Brief, keine E-Mail und keine Einwilligung**.

## Sicherheitsvertrag vor jedem Send

Ein Operator kann ausschließlich eine Referenz auf eine vom Host gepflegte Nachricht vorbereiten: `content_ref`, SHA-256-Fingerprint, `recipient_ref` und eindeutige `reply_id`. Der Inhalt bleibt in der Host-Content-Akte. Ein Herkunftskanal wie CRM_INBOUND oder WEB_FORM ist **keine** Einwilligung. Der tatsächliche Host muss unabhängig feststellen, ob der Empfänger für den konkreten Kanal, diese Anfrage, diesen Zweck und diesen Inhalt zum Zeitpunkt des Versands angeschrieben werden darf. Der `IndependentReplyPermission.check(request)`-Vertrag erwartet eine kurze, gebundene, unabhängige Berechtigungsentscheidung mit Beleg-ID und Ablaufdatum. Diese stammt nicht von einem Chatbot oder dem Frontend.

Zusätzlich verlangt GreenGrapeMe eine **wirkliche PomeloMe AuthorityEnvelope** mit exakten, vom Host gesetzten Constraints für Tenant/Pilot/Case/Recipient/Content-Hash/Kanal/Zweck und passenden Fähigkeiten. PomeloMe muss die irreversible Aktion plus `tool:greengrapeme.send_authorized_reply`, `effect:irreversible`, `communication:reply`, `purpose:inbound-response` selbst autorisieren. Die externe Adapter-Implementierung muss unmittelbar am Sendepunkt erneut unabhängig Empfänger-/Consent-/Suppressionstatus und Content-Hash kontrollieren. **Weder das lokale GreenGrapeMe-SQLite noch PomeloMe kann ein rechtlich verbindliches Cross-Process-Atomicity zwischen Opt-out und Provider-Send allein garantieren.** Ohne abschließenden Adapter-Check ist der reale Providerbetrieb nicht freigegeben.

## Persistenz und Crash-Grenzen

Ein Reply wird unter `(tenant,pilot,case,reply_id)` mit einer deterministischen PomeloMe-`effect_id` gespeichert. `prepare` persistiert nur `PREPARED`, null Versuche. `dispatch` prüft aktualisierte Case- und Opportunity-Quellenfingerprints, jeden aktuellen Opt-out, Host-Permission und Pomelo Authority, legt **vor der Gateway-Grenze** `DISPATCH_IN_FLIGHT` dauerhaft ab und ruft genau einmal `EffectGateway.execute` auf.

Danach:
- `PROVIDER_ACCEPTED`: PomeloMe hat einen erfolgreichen, reconcilierten Provider-Receipt mit externer Message-ID geliefert. **Dies beweist weder Zustellung noch tatsächliches Lesen.**
- `PROVIDER_FAILED`: PomeloMe meldet reconciliert eine fehlgeschlagene Aktion.
- `DISPATCH_UNCERTAIN`: Antwort verloren, unklarer Gateway-Status oder Absturz. **Kein neuer Dispatch!** Reconciliation liest ausschließlich die aktuelle PomeloMe-Store-Observation; ohne passenden Receipt bleibt dieser Zustand gesperrt.

Die echte PomeloMe-Gateway-Ledger-Verarbeitung, Probe und weitere zulässige Recovery erfolgen vollständig innerhalb PomeloMe, nicht durch einen neuen GreenGrapeMe-Worker. Erst der tatsächliche Provider-Beleg darf die lokale Projektion vervollständigen. **Ohne passende Quellfreigabe keine Sendefunktion.**

## Bedienung und Release

Der bestehende lokale Operator-CLI bietet `pilot-reply-prepare` (nur vorbereiten) und `pilot-replies` (nur Status lesen). Der lokale Browser besitzt ausschließlich `GET /api/pilot-replies?pilot=...&case=...`. **Es gibt ausdrücklich keinen CLI-/HTTP-Endpunkt für `dispatch`, `permission.check` oder Receipt-Fabrication**. Die Host-Anwendung muss selbst einen isolierten, autorisierten Service bereitstellen, um die Python-`dispatch`-Methode mit ihren geprüften PomeloMe-Objekten aufzurufen.

Beispiel mit einem bereits existierenden Pilotfall:

```bash
PYTHONPATH=src python -m greengrapeme.cli --tenant <trusted-tenant> --db sales.db \
  pilot-reply-prepare --pilot-id pilot-0001 --case-id inbound-0001 \
  --reply-id reply-0001 \
  --recipient-ref urn:crm:recipient:verified-001 \
  --content-ref urn:content:approved-reply-001 \
  --content-sha256 <64-hex-sha256>
```

**Nächste zwingende Abnahmen:** tatsächliche Host-Permission/Consent-Engine, konkret angebundener Provider-/Pomelo-Adapter einschließlich Adapter-seitiger letzter Prüfung, Live-FruitStack-Host-Test und effektiver Opt-out-Latenzmessung. Erst danach darf ein realer Versandtest unter expliziter Freigabe durchgeführt werden. Kein autonomer Outbound, kein KI-generiertes Contact Grant, keine faktischen Umsätze und kein öffentliches SaaS-Deployment werden behauptet.
