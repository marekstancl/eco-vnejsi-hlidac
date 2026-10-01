#!/usr/bin/env python3
"""Hlidac eco mimo domov (GitHub Actions, kazdych 30 min).

Vsechno ostatni hlidani eco bezi doma; kdyz vypadne domov (proud, internet),
je ticho. Tenhle skript bezi na serverech GitHubu a hlida dve veci:
  1. verejne weby z weby.json (PublicWebDown, critical),
  2. servery v Hetzneru, ktere bezi bez stitku eco_trvaly=ano dele nez 6 h
     (HetznerSirotek, critical - 6. 9. 2026 tak bezel server 21 dni).
Vlastni chyba (API, konfigurace) = VnejsiHlidacChyba (warning) + ping /fail.
Zastaveny workflow pozna healthchecks.io (chybejici ping).

Epizoda: prvni vyskyt = zprava hned, pak 1x denne, konec = RESOLVED.
Stav v stav.json (klic, casy, ID/host/scope - nic vic, cache verejneho repa
mohou cist i workflow z forku), prenasi se pres actions/cache.
Zprava se do stavu zapise az po uspesnem odeslani.
"""
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEN = timedelta(days=1)
SIROTEK_PO = timedelta(hours=6)
UA = {"User-Agent": "eco-vnejsi-hlidac/1"}


def zkontroluj_web(web, otevri=urllib.request.urlopen, spi=time.sleep, pokusy=3, pauza=20):
    """None = web odpovida ocekavanym kodem; jinak popis posledni chyby."""
    chyba = None
    for i in range(pokusy):
        try:
            with otevri(urllib.request.Request(web["url"], headers=UA), timeout=15) as r:
                kod = r.status
        except urllib.error.HTTPError as e:
            kod = e.code
        except Exception as e:  # timeout, DNS, TLS, spojeni
            kod, chyba = None, f"{type(e).__name__}: {e}"[:200]
        if kod in web["kody"]:
            return None
        if kod is not None:
            chyba = f"HTTP {kod}"
        if i < pokusy - 1:
            spi(pauza)
    return chyba


def nacti_servery(token, otevri=urllib.request.urlopen):
    """Vsechny servery ze vsech stranek Hetzner API (vyjimka = chyba hlidace)."""
    servery, stranka = [], 1
    while stranka:
        req = urllib.request.Request(
            f"https://api.hetzner.cloud/v1/servers?page={stranka}&per_page=50",
            headers={**UA, "Authorization": f"Bearer {token}"})
        with otevri(req, timeout=20) as r:
            data = json.load(r)
        if not isinstance(data.get("servers"), list):
            raise ValueError("Hetzner API: chybi seznam servers")
        servery += data["servers"]
        stranka = data.get("meta", {}).get("pagination", {}).get("next_page")
    return servery


def sirotci(servery, ted):
    vysledek = {}
    for s in servery:
        if s.get("status") != "running" or (s.get("labels") or {}).get("eco_trvaly") == "ano":
            continue
        vznik = datetime.fromisoformat(s["created"].replace("Z", "+00:00"))
        if ted - vznik >= SIROTEK_PO:
            hodin = int((ted - vznik).total_seconds() // 3600)
            vysledek[f"hetzner:{s['id']}"] = {
                "id": "HetznerSirotek", "severity": "critical", "host": "hetzner", "scope": s["name"],
                "co": f"Server {s['name']} v Hetzneru běží {hodin} h a nemá štítek eco_trvaly=ano. Stojí peníze.",
                "akce": "Pokud nejde o probíhající výpadek proudu: ověř a smaž server (hcloud server delete), "
                        "nebo mu dej štítek eco_trvaly=ano, pokud má běžet trvale.",
                "kontext": f"id={s['id']}, vytvořen {s['created']}"}
    return vysledek


def minimum(p):
    """Do stavu (cache verejneho repa) jen to, co je potreba na RESOLVED."""
    return {k: p[k] for k in ("id", "severity", "host", "scope")}


def nacti_stav(cesta="stav.json"):
    try:
        with open(cesta) as f:
            stav = json.load(f)
        if isinstance(stav, dict) and all({"od", "posledni", "problem"} <= set(v) for v in stav.values()):
            return stav
    except (OSError, ValueError, TypeError):
        pass
    return {}  # ztraceny/poskozeny stav = zacit znovu (radeji zprava navic nez ticho)


def problem_webu(web, chyba):
    return {"id": "PublicWebDown", "severity": "critical", "host": web["host"], "scope": web["projekt"],
            "co": f"{web['url']} zvenku neodpovídá ({chyba}). Zákazníci vidí chybu.",
            "akce": "Hned: skill obnova-ziveho-webu (ssh eco-prod, docker ps -a, docker logs). "
                    "Nedostupné vše najednou = výpadek domova (proud/internet).",
            "kontext": f"služba {web['sluzba']}, 3 pokusy po 20 s z GitHub Actions"}


def problem_hlidace(co):
    return {"id": "VnejsiHlidacChyba", "severity": "warning", "host": "github-actions", "scope": "vnejsi-hlidac",
            "co": co, "akce": "Oprav konfiguraci nebo token v GitHub Secrets repa eco-vnejsi-hlidac; "
                              "dokud to trvá, Hetzner se zvenku nehlídá.",
            "kontext": "běh ve workflow hlidac"}


def rozhodni(stav, problemy, ted):
    """Vrati [(druh, klic, problem)]; druh: novy | denni | konec."""
    zpravy = []
    for klic, p in problemy.items():
        if klic not in stav:
            zpravy.append(("novy", klic, p))
        elif ted - datetime.fromisoformat(stav[klic]["posledni"]) >= DEN:
            zpravy.append(("denni", klic, p))
    for klic, zaznam in stav.items():
        if klic not in problemy:
            zpravy.append(("konec", klic, zaznam["problem"]))
    return zpravy


def text_zpravy(druh, p, stav_klice, ted):
    if druh == "konec":
        hlava, co = "✅ <b>[RESOLVED]</b>", f"Už v pořádku: {p['id']} ({p['scope']})."
        akce = "nic"
    else:
        emoji = "🔴" if p["severity"] == "critical" else "⚠️"
        hlava = f"{emoji} <b>[{p['severity'].upper()}] FIRING</b>"
        co = p.get("co", f"{p['id']} ({p['scope']}) trvá, aktuální stav teď nejde ověřit.")
        akce = p.get("akce", "viz předchozí zpráva")
    kontext = p.get("kontext", "")
    if druh == "denni":
        trva = ted - datetime.fromisoformat(stav_klice["od"])
        kontext += f" | trvá {trva.days} d {trva.seconds // 3600} h (denní připomínka)"
    e = html.escape
    return (f"{hlava} · vnejsi-hlidac\n"
            f"Host: <code>{e(p['host'])}</code> | Scope: <code>{e(p['scope'])}</code>\n"
            f"ID: <code>{e(p['id'])}</code>\n\n"
            f"<b>Co:</b> {e(co)}\n<b>Akce:</b> {e(akce)}\n<b>Kontext:</b> {e(kontext)}")


def posli_telegram(text, otevri=urllib.request.urlopen):
    token, chat = os.environ["TELEGRAM_ALERT_BOT_TOKEN"], os.environ["TELEGRAM_ALERT_CHAT_ID"]
    data = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                 headers={**UA, "Content-Type": "application/json"})
    with otevri(req, timeout=20) as r:
        if not json.load(r).get("ok"):
            raise RuntimeError("Telegram odmitl zpravu")


def ping(url, uspech, otevri=urllib.request.urlopen):
    if not url:
        return
    try:
        otevri(urllib.request.Request(url if uspech else url.rstrip("/") + "/fail", headers=UA), timeout=10).close()
    except Exception as e:
        print(f"healthchecks ping selhal: {type(e).__name__}", file=sys.stderr)


def beh(weby, stav, ted, token, hc_url, otevri=urllib.request.urlopen, spi=time.sleep, posli=None):
    """Jeden beh. Vrati (novy_stav, exit_kod)."""
    posli = posli or (lambda t: posli_telegram(t, otevri))
    problemy, chyba_hlidace = {}, None
    for w in weby:
        chyba = zkontroluj_web(w, otevri, spi)
        if chyba:
            problemy[f"web:{w['url']}"] = problem_webu(w, chyba)
    if not token:
        chyba_hlidace = "Chybí HCLOUD_READ_TOKEN – servery v Hetzneru se zvenku nehlídají."
    else:
        try:
            problemy.update(sirotci(nacti_servery(token, otevri), ted))
        except Exception as e:
            chyba_hlidace = f"Hetzner API nejde přečíst ({type(e).__name__}) – nevím, jestli tam něco běží."
            # bez ctení API nevime, jestli sirotek skoncil: nechame jeho epizody otevrene
            for klic in [k for k in stav if k.startswith("hetzner:")]:
                problemy[klic] = stav[klic]["problem"]
    if not hc_url:
        chyba_hlidace = (chyba_hlidace + " " if chyba_hlidace else "") + \
            "Chybí HC_VNEJSI_HLIDAC_URL – zastavení hlídače nikdo nepozná."
    if chyba_hlidace:
        problemy["hlidac"] = problem_hlidace(chyba_hlidace)

    novy, selhalo_odeslani = dict(stav), False
    for druh, klic, p in rozhodni(stav, problemy, ted):
        try:
            posli(text_zpravy(druh, p, stav.get(klic), ted))
        except Exception as e:
            print(f"odeslani {klic} selhalo: {type(e).__name__}", file=sys.stderr)
            selhalo_odeslani = True
            continue
        if druh == "konec":
            novy.pop(klic, None)
        else:
            novy[klic] = {"od": stav.get(klic, {}).get("od", ted.isoformat()),
                          "posledni": ted.isoformat(), "problem": minimum(p)}
    kod = 1 if (chyba_hlidace or selhalo_odeslani) else 0
    ping(hc_url, kod == 0, otevri)
    return novy, kod


def main():
    for v in ("TELEGRAM_ALERT_BOT_TOKEN", "TELEGRAM_ALERT_CHAT_ID"):
        if not os.environ.get(v):
            print(f"Chybi {v} - nelze nic ohlasit", file=sys.stderr)
            ping(os.environ.get("HC_VNEJSI_HLIDAC_URL"), False)
            return 1
    hc = os.environ.get("HC_VNEJSI_HLIDAC_URL")
    try:
        with open("weby.json") as f:
            weby = json.load(f)
        if not all({"url", "projekt", "sluzba", "host", "kody"} <= set(w) for w in weby):
            raise ValueError("polozka bez povinneho pole")
        novy, kod = beh(weby, nacti_stav(), datetime.now(timezone.utc), os.environ.get("HCLOUD_READ_TOKEN"), hc)
        with open("stav.json", "w") as f:
            json.dump(novy, f, ensure_ascii=False, indent=1)
    except Exception as e:  # cokoli necekaneho = zprava hned, ne az chybejici ping
        try:
            posli_telegram(text_zpravy("novy", problem_hlidace(
                f"Hlídač spadl ({type(e).__name__}: {str(e)[:120]}) – weby ani Hetzner se zvenku nehlídají."),
                None, datetime.now(timezone.utc)))
        finally:
            ping(hc, False)
        raise
    print(f"weby: {len(weby)}, otevrene epizody: {sorted(novy)}, exit {kod}")
    return kod


if __name__ == "__main__":
    sys.exit(main())
