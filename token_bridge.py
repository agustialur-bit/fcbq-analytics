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
import socket
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
        # Private Network Access: Chrome tracta una crida d'una web pública
        # (basquetcatala.cat) cap a 127.0.0.1 com a accés a xarxa privada i hi
        # fa un preflight que exigeix aquesta capçalera. Sense ella el
        # bookmarklet no arribaria mai al receptor.
        self.send_header("Access-Control-Allow-Private-Network", "true")
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
    """Arrenca el receptor en segon pla. Retorna un text per mostrar a l'app.

    A Windows, SO_REUSEADDR deixa que dos processos lliguin el mateix port
    sense error: el segon creuria que escolta mentre el primer es queda les
    peticions (i potser amb codi antic). Per això es comprova primer si algú
    ja hi respon, en lloc de confiar que el bind falli."""
    with socket.socket() as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            return f"ja hi ha un altre receptor al port {PORT}"
    try:
        servidor = HTTPServer(("127.0.0.1", PORT), _Receptor)
    except OSError as e:
        return f"no escoltant ({e.strerror or e})"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"escoltant a 127.0.0.1:{PORT}"


# Bookmarklet. Va tot en una sola línia perquè és una URL javascript:, així que
# cap literal pot contenir un salt de línia de debò.
#
# basquetcatala.cat NO desa el token a localStorage/sessionStorage/cookies —
# se'l queda a la memòria de JavaScript. Per això mirar els magatzems no
# n'hi ha prou: el bookmarklet també intercepta la capçalera Authorization de
# les peticions que la pàgina fa tota sola. És el mateix que es feia a mà amb
# F12 → Network, sense tocar el reCAPTCHA: només llegeix una credencial que el
# navegador ja té i ja està fent servir.
#
# Flux: 1r clic → si el troba als magatzems, l'entrega; si no, instal·la els
# hooks i demana a l'usuari que cliqui una pestanya del partit. Quan la pàgina
# fa la següent petició, el captura i mostra un requadre amb el botó de copiar
# (el porta-retalls necessita un clic de l'usuari; l'enviament al receptor
# local, no).
BOOKMARKLET = (
    "javascript:(function(){var W=window;"
    r"var re=/eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/;"
    "function pl(x){return JSON.parse(atob(x.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')))}"
    "function viu(t){try{var p=pl(t);return !!(p.exp&&p.exp*1000>Date.now())}catch(e){return false}}"
    "function mag(){var s=[];"
    "try{for(var i=0;i<localStorage.length;i++)s.push(localStorage.getItem(localStorage.key(i)))}catch(e){}"
    "try{for(var i=0;i<sessionStorage.length;i++)s.push(sessionStorage.getItem(sessionStorage.key(i)))}catch(e){}"
    "s.push(document.cookie);"
    "for(var i=0;i<s.length;i++){var m=(s[i]||'').match(re);if(m&&viu(m[0]))return m[0]}return null}"
    "function bn(h){var d=document.getElementById('mkB')||document.createElement('div');d.id='mkB';"
    "d.style.cssText='position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:330px;"
    "background:#185FA5;color:#fff;font:13px/1.5 system-ui,sans-serif;padding:14px 16px;"
    "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.35)';d.innerHTML=h;"
    "document.body.appendChild(d);return d}"
    "function bo(t){var b=document.getElementById('mkC');if(!b)return;b.onclick=function(){"
    "navigator.clipboard.writeText(t).then(function(){b.textContent='Copiat!'},"
    "function(){window.prompt('Copia aquest token:',t)})}}"
    "function ent(t){var min=Math.round((pl(t).exp*1000-Date.now())/60000);"
    "var btn='<button id=\"mkC\" style=\"margin-top:10px;padding:7px 12px;border:0;border-radius:6px;"
    "cursor:pointer;font-weight:600\">Copia per a l app del nuvol</button>';"
    "function fi(loc){bn('<b>Token trobat</b> ('+min+' min de vida).<br>App local: '+loc+btn);bo(t)}"
    "fetch('http://127.0.0.1:" + str(PORT) + "/token',{method:'POST',body:t})"
    ".then(function(r){fi(r.ok?'ja el te.':'no l ha acceptat.')})"
    ".catch(function(){fi('no s esta executant.')})}"
    "var t=W.__mkTok||mag();"
    "if(t&&viu(t)){ent(t);return}"
    "if(W.__mkHook){bn('<b>Encara no he vist cap peticio amb token.</b><br>Clica una pestanya del "
    "partit (Estadistiques, Jugades...) <u>sense recarregar</u> la pagina.');return}"
    "W.__mkHook=1;"
    "function mira(v){if(!v||W.__mkTok)return;var m=String(v).match(re);"
    "if(m&&viu(m[0])){W.__mkTok=m[0];ent(m[0])}}"
    "var sh=XMLHttpRequest.prototype.setRequestHeader;"
    "XMLHttpRequest.prototype.setRequestHeader=function(k,v){"
    "try{if(String(k).toLowerCase()==='authorization')mira(v)}catch(e){}"
    "return sh.apply(this,arguments)};"
    "var of=W.fetch;W.fetch=function(a,b){try{var h=(b&&b.headers)||(a&&a.headers);"
    "if(h){if(h.get)mira(h.get('authorization'));"
    "else Object.keys(h).forEach(function(k){if(k.toLowerCase()==='authorization')mira(h[k])})}}catch(e){}"
    "return of.apply(this,arguments)};"
    "bn('<b>Escoltant...</b><br>Ara clica una pestanya del partit (Estadistiques, Jugades...) "
    "<u>sense recarregar</u> la pagina. El token apareixera aqui.')"
    "})()"
)
