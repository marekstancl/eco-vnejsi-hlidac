"""Testy hlidace bez site: podvrzene otevirani URL, cas a odesilani."""
import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

import hlidac

TED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
WEB = {"url": "https://a.cz/", "projekt": "a", "sluzba": "a-web", "host": "eco-prod", "kody": [200]}
MCP = {"url": "https://m.cz/mcp", "projekt": "m", "sluzba": "m-mcp", "host": "eco-prod", "kody": [401]}


class Odpoved(io.BytesIO):
    def __init__(self, status=200, telo=b"{}"):
        super().__init__(telo)
        self.status = status


def server(id_, hodin, status="running", stitky=None):
    return {"id": id_, "name": f"s{id_}", "status": status, "labels": stitky or {},
            "created": (TED - timedelta(hours=hodin)).isoformat().replace("+00:00", "Z")}


class Svet:
    """Podvrzeny internet: kody webu, stranky Hetzneru, pingy."""
    def __init__(self, weby=None, servery=(), api_chyba=False):
        self.weby, self.servery, self.api_chyba, self.pingy, self.zpravy = weby or {}, list(servery), api_chyba, [], []

    def otevri(self, req, timeout=None):
        url = req.full_url
        if "hc-ping" in url:
            self.pingy.append(url)
            return Odpoved()
        if "hetzner" in url:
            if self.api_chyba:
                raise urllib.error.HTTPError(url, 401, "x", {}, None)
            stranka = int(url.split("page=")[1].split("&")[0])
            kus = self.servery[(stranka - 1) * 2:stranka * 2]  # 2 na stranku: testuje strankovani
            dalsi = stranka + 1 if len(self.servery) > stranka * 2 else None
            return Odpoved(telo=json.dumps({"servers": kus, "meta": {"pagination": {"next_page": dalsi}}}).encode())
        kod = self.weby.get(url, 200)
        if kod == "timeout":
            raise TimeoutError("timed out")
        if kod >= 400:
            raise urllib.error.HTTPError(url, kod, "x", {}, None)
        return Odpoved(kod)

    def beh(self, weby, stav, ted=TED, token="t", hc="https://hc-ping.com/u"):
        return hlidac.beh(weby, stav, ted, token, hc, otevri=self.otevri, spi=lambda s: None,
                          posli=self.zpravy.append)


class TestWeby(unittest.TestCase):
    def test_zdravy_web_bez_zpravy_a_ping_uspech(self):
        s = Svet()
        stav, kod = s.beh([WEB], {})
        self.assertEqual((stav, kod, s.zpravy), ({}, 0, []))
        self.assertEqual(s.pingy, ["https://hc-ping.com/u"])

    def test_401_u_mcp_je_zivy(self):
        s = Svet(weby={MCP["url"]: 401})
        self.assertEqual(s.beh([MCP], {})[0], {})

    def test_vypadek_critical_hned(self):
        s = Svet(weby={WEB["url"]: 502})
        stav, kod = s.beh([WEB], {})
        self.assertEqual(kod, 0)  # nalez je uspesne provedena kontrola
        self.assertIn("web:https://a.cz/", stav)
        self.assertIn("[CRITICAL] FIRING", s.zpravy[0])
        self.assertIn("PublicWebDown", s.zpravy[0])
        self.assertIn("HTTP 502", s.zpravy[0])

    def test_tri_pokusy_jeden_uspech_neni_vypadek(self):
        pokusy = iter([502, 502, 200])
        s = Svet()
        orig = s.otevri
        s.otevri = lambda req, timeout=None: orig(req) if "a.cz" not in req.full_url else \
            (Odpoved(200) if next(pokusy) == 200 else (_ for _ in ()).throw(urllib.error.HTTPError(req.full_url, 502, "x", {}, None)))
        self.assertEqual(s.beh([WEB], {})[0], {})

    def test_timeout_je_vypadek(self):
        s = Svet(weby={WEB["url"]: "timeout"})
        s.beh([WEB], {})
        self.assertIn("TimeoutError", s.zpravy[0])


class TestNehlidat(unittest.TestCase):
    def test_nehlidany_web_se_nezkousi(self):
        s = Svet(weby={"https://d.cz/": 502})
        w = {"url": "https://d.cz/", "projekt": "d", "sluzba": "d", "host": "eco-dev", "kody": [], "nehlidat": "vyvoj"}
        self.assertEqual(s.beh([w], {})[0], {})


class TestEpizoda(unittest.TestCase):
    def setUp(self):
        self.s = Svet(weby={WEB["url"]: 502})
        self.stav, _ = self.s.beh([WEB], {})
        self.s.zpravy.clear()

    def test_do_24h_ticho(self):
        self.stav, _ = self.s.beh([WEB], self.stav, TED + timedelta(hours=23))
        self.assertEqual(self.s.zpravy, [])

    def test_po_24h_denni_radek(self):
        self.s.beh([WEB], self.stav, TED + timedelta(hours=24, minutes=1))
        self.assertIn("denní připomínka", self.s.zpravy[0])

    def test_konec_resolved_a_vycisteni(self):
        s = Svet()
        stav, _ = s.beh([WEB], self.stav, TED + timedelta(minutes=30))
        self.assertEqual(stav, {})
        self.assertIn("[RESOLVED]", s.zpravy[0])

    def test_neodeslana_zprava_se_nezapise(self):
        s = Svet(weby={WEB["url"]: 502})
        s.zpravy = None
        stav, kod = hlidac.beh([WEB], {}, TED, "t", "https://hc-ping.com/u", otevri=s.otevri,
                               spi=lambda x: None, posli=lambda t: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual((stav, kod), ({}, 1))
        self.assertTrue(s.pingy[-1].endswith("/fail"))


class TestHetzner(unittest.TestCase):
    def test_sirotek_po_6h_i_na_druhe_strance(self):
        s = Svet(servery=[server(1, 1), server(2, 2, stitky={"eco_trvaly": "ano"}), server(3, 7)])
        stav, _ = s.beh([], {})
        self.assertEqual(sorted(stav), ["hetzner:3"])
        self.assertIn("HetznerSirotek", s.zpravy[0])

    def test_zastaveny_a_trvaly_neni_sirotek(self):
        s = Svet(servery=[server(1, 30, status="off"), server(2, 30, stitky={"eco_trvaly": "ano"})])
        self.assertEqual(s.beh([], {})[0], {})

    def test_chyba_api_warning_fail_a_epizoda_sirotka_trva(self):
        s = Svet(servery=[server(3, 7)])
        stav, _ = s.beh([], {})
        s2 = Svet(api_chyba=True)
        stav2, kod = s2.beh([], stav, TED + timedelta(minutes=30))
        self.assertEqual(kod, 1)
        self.assertIn("hetzner:3", stav2)  # bez API nevime, ze skoncil -> zadne RESOLVED
        self.assertNotIn("RESOLVED", "".join(s2.zpravy))
        self.assertIn("VnejsiHlidacChyba", s2.zpravy[0])
        self.assertTrue(s2.pingy[-1].endswith("/fail"))

    def test_chybi_token_je_chyba_hlidace(self):
        s = Svet()
        stav, kod = s.beh([], {}, token=None)
        self.assertEqual(kod, 1)
        self.assertIn("HCLOUD_READ_TOKEN", s.zpravy[0])


class TestStav(unittest.TestCase):
    def test_ztraceny_nebo_poskozeny_stav_je_prazdny(self):
        import os, tempfile
        d = tempfile.mkdtemp()
        for obsah in (None, "nejson", "[]", '{"web:x": {"od": "x"}}'):
            cesta = os.path.join(d, "stav.json")
            if obsah is None:
                cesta = os.path.join(d, "neni.json")
            else:
                open(cesta, "w").write(obsah)
            self.assertEqual(hlidac.nacti_stav(cesta), {}, obsah)

    def test_po_ztrate_stavu_trvajici_vypadek_znovu_ohlasen(self):
        s = Svet(weby={WEB["url"]: 502})
        s.beh([WEB], {})
        s.beh([WEB], {}, TED + timedelta(minutes=30))  # stav ztracen
        self.assertEqual(len(s.zpravy), 2)

    def test_stav_nese_jen_minimum(self):
        s = Svet(weby={WEB["url"]: 502}, servery=[server(3, 7)])
        stav, _ = s.beh([WEB], {})
        for v in stav.values():
            self.assertEqual(set(v["problem"]), {"id", "severity", "host", "scope"})


class TestFormat(unittest.TestCase):
    def test_standard_hlavicka_a_escape(self):
        p = hlidac.problem_hlidace("a <b> & c")
        t = hlidac.text_zpravy("novy", p, None, TED)
        self.assertTrue(t.startswith("⚠️ <b>[WARNING] FIRING</b> · vnejsi-hlidac\nHost: <code>github-actions</code>"))
        self.assertIn("a &lt;b&gt; &amp; c", t)
        for pole in ("ID: ", "<b>Co:</b>", "<b>Akce:</b>", "<b>Kontext:</b>"):
            self.assertIn(pole, t)

    def test_weby_json_platny(self):
        with open("weby.json") as f:
            weby = json.load(f)
        for w in weby:
            self.assertTrue(w["url"].startswith("https://"))
            self.assertTrue(set(w) >= {"url", "projekt", "sluzba", "host", "kody"})
            self.assertTrue(w.get("nehlidat") or w["kody"], w["url"])  # hlidany musi mit kody


if __name__ == "__main__":
    unittest.main()
