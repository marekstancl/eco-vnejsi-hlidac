# eco-vnejsi-hlidac — hlídač mimo domov

## Eco infra kontext

<!-- CC si /opt/eco/CLAUDE.md nacte sam: hosty, Layer 1 a 2, Telegram, zalohy,
     eco-admin, nasazeni. Nic z toho se sem neopisuje. -->

Tenhle repozitář **nic neprovozuje doma**. Běží na serverech GitHubu každých 30 minut
a jeho celý smysl je, že funguje, i když je domov bez proudu nebo bez internetu.
Nemá žádnou databázi, žádný kontejner, žádnou sdílenou službu z eco.

- Hlídá veřejné adresy z `weby.json`, sirotky v Hetzneru a vlastní chyby
- Zprávy jdou Telegramem ve tvaru [standardu alertů](https://docs.aidlab.dev/ecosystem/operations/alerting-and-automation)
- Každý úspěšný běh pingne healthchecks.io; chyba pingne `/fail`

## Konvence tohohle projektu

- **Žádná závislost na domově.** Do kódu nepatří nic, co by potřebovalo eco-dev nebo
  eco-prod - ani čtení souboru, ani síťové volání dovnitř. Tím by hlídač přestal být
  vnější a při výpadku by zmlkl spolu se vším ostatním.
- **Seznam adres je data, ne kód.** Nová adresa = řádek ve `weby.json`
  (`url`, `projekt`, `sluzba`, `host`, `kody`). Vědomě nehlídaná adresa má pole
  `nehlidat` s důvodem, aby bylo poznat rozdíl mezi „zapomněli jsme" a „nechceme".
- **Každá adresa vystavená přes Cloudflare tunel musí být ve `weby.json`** - hlídaná,
  nebo s `nehlidat`. Chybějící adresu denně ohlásí kontrola v repozitáři `services`.
- **MCP za přihlášením se hlídá na `401`,** ne na `200`: odpověď „nejsi přihlášen"
  dokazuje, že služba žije.
- Tajemství (token Telegramu, Hetzneru, adresa healthchecks) jsou výhradně
  v nastavení GitHub Actions. Do repozitáře ani do logu nepatří.

## Tech

Python bez závislostí (standardní knihovna), GitHub Actions. Testy `test_hlidac.py`
spouští `python3 -m pytest` nebo `python3 test_hlidac.py`.

## Struktura

- `hlidac.py` - celý hlídač
- `weby.json` - seznam hlídaných adres
- `test_hlidac.py` - testy
- `posledni-beh.txt` - stopa posledního běhu
- `.github/workflows/` - plán a spouštění

## Jazyk

Komunikuj v češtině, pokud uživatel nezačne anglicky.

## Backlog

Položky patří do ekosystémového backlogu `/opt/eco/services/BACKLOG.md` (číslování
`B-xxx`). Vlastní backlog tenhle projekt nemá.
