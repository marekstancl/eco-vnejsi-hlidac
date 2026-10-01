# eco-vnejsi-hlidac

Hlídač ekosystému eco, který běží **mimo domov** – na serverech GitHubu, každých 30 minut.
Všechno ostatní hlídání eco běží doma; když vypadne proud nebo internet, je ticho. Tenhle hlídač ne.

## Co hlídá

| ID | Kdy | Závažnost |
|---|---|---|
| `PublicWebDown` | web z `weby.json` neodpoví očekávaným kódem ve 3 pokusech po 20 s | critical |
| `HetznerSirotek` | server v Hetzneru běží > 6 h a nemá štítek `eco_trvaly=ano` | critical |
| `VnejsiHlidacChyba` | chybí token nebo URL healthchecks, Hetzner API nejde přečíst, hlídač spadl | warning |

Když nejde odeslat samotná zpráva (Telegram), běh skončí chybou a pingne healthchecks `/fail` – ozve se healthchecks.

Zprávy jdou Telegramem (alert bot eco) ve tvaru standardu eco
(https://docs.aidlab.dev/ecosystem/operations/alerting-and-automation). Opakování: první výskyt
hned, pak jednou denně, konec výpadku = ✅ RESOLVED.

**Kdo hlídá hlídače:** každý úspěšný běh pingne healthchecks.io (`eco-vnejsi-hlidac`, period 30 min,
grace 1 h). Chyba = ping `/fail`. Když GitHub workflow zastaví, healthchecks pošle zprávu e-mailem i Telegramem.

## Jak přidat web
Řádek do `weby.json`: `url`, `projekt`, `sluzba`, `host` (kde web běží), `kody` (např. `[200]`,
MCP za přihlášením `[401]`). Push → testy → od dalšího běhu se hlídá.

## Server, který má v Hetzneru běžet trvale
Štítek `eco_trvaly=ano` (`hcloud server add-label <server> eco_trvaly=ano`). Bez něj je každý
server starší než 6 h hlášen jako sirotek.

## Tajné hodnoty (Settings → Secrets → Actions)
`TELEGRAM_ALERT_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`, `HCLOUD_READ_TOKEN` (Hetzner token **jen pro čtení**),
`HC_VNEJSI_HLIDAC_URL`. V kódu ani v logu nic tajného není; stav (`stav.json`: klíč, časy, ID/host/scope) se přenáší
přes actions/cache – cache veřejného repa nepovažuj za tajnou.

## Provoz
- Testy: `python3 -m unittest -v` (bez sítě). Na GitHubu běží při každém push, ne před ostrou kontrolou.
- Ruční běh: Actions → hlidac → Run workflow.
- Keepalive: GitHub ve veřejném repu vypíná plánované workflow po 60 dnech bez aktivity – workflow
  `keepalive` jednou měsíčně commitne `posledni-beh.txt`.
