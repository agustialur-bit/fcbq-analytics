# -*- coding: utf-8 -*-
"""Pont per renovar el token de l'API sense haver de rebuscar-lo al navegador.

basquetcatala.cat protegeix tot el web amb un reCAPTCHA i emet el token de
l'API (JWT de 2 h) només un cop passat. Això vol dir que el token l'ha
d'obtenir una persona amb un navegador de debò — no es pot automatitzar sense
saltar-se la protecció anti-bot, i no ho fem.

El que sí que estalviem és el F12 → Network → copiar la capçalera. El
bookmarklet d'aquí sota llegeix el token que la pàgina ja té i:

  * el copia sempre al porta-retalls, que és l'única via que funciona amb
    l'app desplegada al núvol (allà el navegador no arriba al localhost del
    contenidor, i el fitxer d'aquí sota no hi és mai);
  * a més l'envia al receptor local, si l'app s'està executant a l'ordinador.
    Llavors la recull sola i no cal enganxar res.

L'avís del bookmarklet diu què ha passat a cada banda, perquè no sembli que
l'app del núvol ja té el token quan en realitat no el té.
"""
import os
import json
import base64
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8765
ORIGEN = "https://www.basquetcatala.cat"
FITXER_TOKEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fcbq_token")


def segons_restants(token):
    """Segons que queden abans que caduqui el token (None si no es pot llegir)."""
    try:
        payload = token.split(".")[1]
        dades = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(dades["exp"]) - int(datetime.now().timestamp())
    except Exception:
        return None


def llegeix_token():
    """Token desat pel bookmarklet, o "" si no n'hi ha o ja ha caducat."""
    try:
        with open(FITXER_TOKEN, encoding="utf-8") as f:
            token = f.read().strip()
    except Exception:
        return ""
    seg = segons_restants(token)
    return token if (seg is not None and seg > 0) else ""


def esborra_token():
    try:
        os.remove(FITXER_TOKEN)
    except Exception:
        pass


class _Receptor(BaseHTTPRequestHandler):
    def _cors(self, codi=200):
        self.send_response(codi)
        self.send_header("Access-Control-Allow-Origin", ORIGEN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
        self._cors()

    def do_POST(self):
        if self.path != "/token":
            self._cors(404)
            return
        try:
            mida = int(self.headers.get("Content-Length") or 0)
            token = self.rfile.read(min(mida, 8192)).decode("utf-8").strip()
        except Exception:
            self._cors(400)
            return
        # Només acceptem una cosa que sigui un JWT viu de debò.
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        seg = segons_restants(token)
        if token.count(".") != 2 or seg is None or seg <= 0:
            self._cors(400)
            return
        try:
            with open(FITXER_TOKEN, "w", encoding="utf-8") as f:
                f.write(token)
            os.chmod(FITXER_TOKEN, 0o600)  # no fa res a Windows, sí a Streamlit Cloud
        except Exception:
            self._cors(500)
            return
        self._cors(200)

    def log_message(self, *args):
        pass  # sense soroll als logs de Streamlit


def es_al_nuvol():
    """True si l'app corre a Streamlit Cloud, que munta el repo a /mount/src.
    Allà el receptor no serveix de res: el navegador de l'usuari no arriba al
    localhost del contenidor, i el token s'ha d'enganxar a mà."""
    return os.path.abspath(__file__).replace("\\", "/").startswith("/mount/src")


def inicia_receptor():
    """Arrenca el receptor en segon pla. Retorna un text per mostrar a l'app."""
    try:
        servidor = HTTPServer(("127.0.0.1", PORT), _Receptor)
    except OSError as e:
        return f"no escoltant ({e.strerror or e})"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"escoltant a 127.0.0.1:{PORT}"


# Bookmarklet. Va tot en una sola línia perquè és una URL javascript:, així que
# cap literal pot contenir un salt de línia de debò — els avisos porten \n
# escapat (per això les cadenes raw d'aquí sota).
BOOKMARKLET = (
    "javascript:(function(){"
    r"var re=/eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/,t=null,s=[];"
    "try{for(var i=0;i<localStorage.length;i++)s.push(localStorage.getItem(localStorage.key(i)))}catch(e){}"
    "try{for(var i=0;i<sessionStorage.length;i++)s.push(sessionStorage.getItem(sessionStorage.key(i)))}catch(e){}"
    "s.push(document.cookie);"
    "function pl(x){return JSON.parse(atob(x.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')))}"
    "for(var i=0;i<s.length&&!t;i++){var m=(s[i]||'').match(re);if(!m)continue;"
    "try{var p=pl(m[0]);if(p.exp&&p.exp*1000>Date.now())t=m[0]}catch(e){}}"
    r"if(!t){alert('No he trobat cap token viu.\n\nObre primer les estadistiques d un partit, "
    r"i espera que es vegin les dades (no la pantalla de verificacio).');return}"
    "var min=Math.round((pl(t).exp*1000-Date.now())/60000);"
    r"function avis(loc){alert('Token copiat al porta-retalls ('+min+' min de vida).\n\n"
    r"APP AL NUVOL: enganxa l al camp Token API de la barra lateral.\n"
    r"APP LOCAL: '+loc)}"
    "navigator.clipboard.writeText(t).then(function(){"
    "fetch('http://127.0.0.1:" + str(PORT) + "/token',{method:'POST',body:t})"
    ".then(function(r){avis(r.ok?'ja el te, no cal fer res mes.':'no l ha acceptat.')})"
    ".catch(function(){avis('no s esta executant ara mateix.')})"
    "},function(){window.prompt('Copia aquest token:',t)});"
    "})()"
)
