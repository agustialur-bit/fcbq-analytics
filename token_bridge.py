# -*- coding: utf-8 -*-
"""Pont per rebre el token de l'API sense haver-lo de copiar a mà.

basquetcatala.cat protegeix tot el web amb un reCAPTCHA i emet el token de
l'API (JWT de 2 h) només un cop passat. Això vol dir que el token l'ha
d'obtenir una persona amb un navegador de debò — no es pot automatitzar sense
saltar-se la protecció anti-bot, i no ho fem.

El que sí que estalviem és el F12 → Network → copiar la capçalera: el
bookmarklet d'aquí sota llegeix el token que la pàgina ja té i l'envia a
aquest receptor, que escolta només a 127.0.0.1 i el desa a `.fcbq_token`.
L'app el recull sola a la següent interacció.

Si el receptor no hi és (per exemple amb l'app desplegada a Streamlit Cloud,
on el navegador no arriba al localhost del contenidor), el bookmarklet es
queda el token al porta-retalls i només cal enganxar-lo.
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
            os.chmod(FITXER_TOKEN, 0o600)
        except Exception:
            self._cors(500)
            return
        self._cors(200)

    def log_message(self, *args):
        pass  # sense soroll als logs de Streamlit


def inicia_receptor():
    """Arrenca el receptor en segon pla. Retorna un text per mostrar a l'app.
    Es pot cridar més d'un cop sense problema (si el port ja està ocupat, ho diu)."""
    try:
        servidor = HTTPServer(("127.0.0.1", PORT), _Receptor)
    except OSError as e:
        return f"no escoltant ({e.strerror or e})"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"escoltant a 127.0.0.1:{PORT}"


# Bookmarklet: busca un JWT viu a localStorage / sessionStorage / cookies de
# basquetcatala.cat i l'envia al receptor; si no hi arriba, el copia.
BOOKMARKLET = (
    "javascript:(function(){"
    "var re=/eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+/,t=null,s=[];"
    "try{for(var i=0;i<localStorage.length;i++)s.push(localStorage.getItem(localStorage.key(i)))}catch(e){}"
    "try{for(var i=0;i<sessionStorage.length;i++)s.push(sessionStorage.getItem(sessionStorage.key(i)))}catch(e){}"
    "s.push(document.cookie);"
    "for(var i=0;i<s.length&&!t;i++){var m=(s[i]||'').match(re);if(!m)continue;"
    "try{var p=JSON.parse(atob(m[0].split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));"
    "if(p.exp&&p.exp*1000>Date.now())t=m[0]}catch(e){}}"
    "if(!t){alert('No he trobat cap token viu. Obre primer les estadistiques d un partit i torna-ho a provar.');return}"
    "fetch('http://127.0.0.1:" + str(PORT) + "/token',{method:'POST',body:t})"
    ".then(function(r){if(!r.ok)throw 0;alert('Token enviat a Analitica. Ja pots tornar a l app.')})"
    ".catch(function(){navigator.clipboard.writeText(t).then(function(){"
    "alert('L app no escolta al port " + str(PORT) + ". Token copiat al porta-retalls: enganxa l a la barra lateral.')})});"
    "})()"
)
