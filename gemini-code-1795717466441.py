import hashlib
import json
import os
import random
from typing import Optional

import networkx as nx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

app = FastAPI(title="Rumbo MVP - Trinity Protocol")

# --- Configuración de Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None
GEMINI_MODEL = "gemini-2.5-flash"

# --- Perfiles y Credenciales Virtuales (en memoria para MVP) ---
USUARIOS_DB: dict[str, dict] = {
    "RMB-4821": {
        "folio": "RMB-4821",
        "nombre": "Caleb Silva",
        "color_favorito": "verde",
        "pin_hash": hashlib.sha256("4821".encode()).hexdigest(),
        "vehiculo": "Triciclo",
        "saldo_mxn": 245.0,
        "kg_reciclados": 128.0,
        "co2_evitado_kg": 42.0,
        "nivel": "Oro",
        "verificado": True,
    }
}

# --- Grafo Urbano de Recolección y Centros de Acopio ---
VEHICULO_CONFIG = {
    "A pie": {"max_kg": 18.0, "radio_km": 2.5, "factor_esfuerzo": 1.4},
    "Diablito": {"max_kg": 45.0, "radio_km": 4.0, "factor_esfuerzo": 1.15},
    "Triciclo": {"max_kg": 120.0, "radio_km": 7.0, "factor_esfuerzo": 0.9},
    "Camioneta": {"max_kg": 450.0, "radio_km": 15.0, "factor_esfuerzo": 0.7},
}

TARIFAS_BASE_MXN_KG = {
    "PET": 9.50,
    "Cartón": 3.80,
    "Aluminio": 24.00,
    "Vidrio": 2.20,
    "Chatarra": 6.50,
}

CO2_FACTOR_POR_KG = {
    "PET": 1.5,
    "Cartón": 0.9,
    "Aluminio": 8.2,
    "Vidrio": 0.3,
    "Chatarra": 1.8,
}


def construir_grafo_urbano() -> nx.Graph:
    g = nx.Graph()
    nodos = [
        ("N0", {"nombre": "Tu ubicación actual", "tipo": "inicio", "material": None, "kg": 0.0, "demanda": 1.0, "lat": 19.633, "lon": -99.104}),
        ("N1", {"nombre": "Punto Norte · Av. Mexiquense", "tipo": "recoleccion", "material": "PET", "kg": 16.0, "demanda": 1.25, "lat": 19.641, "lon": -99.106}),
        ("N2", {"nombre": "Mercado San Francisco", "tipo": "recoleccion", "material": "Cartón", "kg": 24.0, "demanda": 1.15, "lat": 19.636, "lon": -99.098}),
        ("N3", {"nombre": "Taller & Escuelas Oriente", "tipo": "recoleccion", "material": "Aluminio", "kg": 9.0, "demanda": 1.35, "lat": 19.631, "lon": -99.095}),
        ("A1", {"nombre": "Centro de Acopio Coacalco", "tipo": "acopio", "material": "PET", "kg": 0.0, "demanda": 1.30, "lat": 19.638, "lon": -99.101}),
        ("A2", {"nombre": "Acopio Central Circular", "tipo": "acopio", "material": "Cartón", "kg": 0.0, "demanda": 1.20, "lat": 19.629, "lon": -99.103}),
    ]
    for node_id, attrs in nodos:
        g.add_node(node_id, **attrs)

    aristas = [
        ("N0", "N1", 1.1),
        ("N0", "N2", 1.4),
        ("N0", "A2", 1.2),
        ("N1", "A1", 0.9),
        ("N1", "N2", 1.3),
        ("N2", "N3", 1.0),
        ("N2", "A1", 1.1),
        ("N3", "A2", 1.2),
        ("A1", "A2", 1.5),
    ]
    for u, v, dist_km in aristas:
        g.add_edge(u, v, distancia_km=dist_km)
    return g


GRAFO_URBANO = construir_grafo_urbano()


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode()).hexdigest()


def _normalizar_clave(nombre: str, color: str) -> str:
    return f"{nombre.strip().lower()}|{color.strip().lower()}"


class RegistroRequest(BaseModel):
    nombre: str
    color_favorito: str
    vehiculo: str = "Triciclo"


class LoginRequest(BaseModel):
    folio: str
    pin: str


class RecuperarRequest(BaseModel):
    nombre: str
    color_favorito: str


class RutaRequest(BaseModel):
    vehiculo: str = "Triciclo"
    material_preferido: Optional[str] = None


@app.post("/api/auth/registro")
def registrar_usuario(req: RegistroRequest):
    vehiculo = req.vehiculo if req.vehiculo in VEHICULO_CONFIG else "Triciclo"
    while True:
        folio = f"RMB-{random.randint(1000, 9999)}"
        if folio not in USUARIOS_DB:
            break
    pin = f"{random.randint(1000, 9999)}"
    perfil = {
        "folio": folio,
        "nombre": req.nombre.strip(),
        "color_favorito": req.color_favorito.strip().lower(),
        "pin_hash": _hash_pin(pin),
        "vehiculo": vehiculo,
        "saldo_mxn": 0.0,
        "kg_reciclados": 0.0,
        "co2_evitado_kg": 0.0,
        "nivel": "Bronce",
        "verificado": True,
    }
    USUARIOS_DB[folio] = perfil
    return {
        "mensaje": "Credencial virtual creada sin necesidad de teléfono o correo.",
        "folio": folio,
        "pin": pin,
        "perfil": {k: v for k, v in perfil.items() if k != "pin_hash"},
    }


@app.post("/api/auth/login")
def iniciar_sesion(req: LoginRequest):
    folio = req.folio.strip().upper()
    user = USUARIOS_DB.get(folio)
    if not user or user["pin_hash"] != _hash_pin(req.pin):
        raise HTTPException(status_code=401, detail="Folio o PIN incorrecto.")
    return {"perfil": {k: v for k, v in user.items() if k != "pin_hash"}}


@app.post("/api/auth/recuperar")
def recuperar_cuenta(req: RecuperarRequest):
    objetivo = _normalizar_clave(req.nombre, req.color_favorito)
    for user in USUARIOS_DB.values():
        actual = _normalizar_clave(user["nombre"], user["color_favorito"])
        if actual == objetivo:
            nuevo_pin = f"{random.randint(1000, 9999)}"
            user["pin_hash"] = _hash_pin(nuevo_pin)
            return {
                "mensaje": "Cuenta recuperada con éxito. Se generó un nuevo PIN.",
                "folio": user["folio"],
                "nuevo_pin": nuevo_pin,
                "perfil": {k: v for k, v in user.items() if k != "pin_hash"},
            }
    raise HTTPException(status_code=404, detail="No encontramos un perfil con ese nombre y color favorito.")


@app.post("/api/ruta/calcular")
def calcular_ruta(req: RutaRequest):
    vehiculo = req.vehiculo if req.vehiculo in VEHICULO_CONFIG else "Triciclo"
    cfg = VEHICULO_CONFIG[vehiculo]
    max_kg = cfg["max_kg"]

    candidatos = []
    for node_id, data in GRAFO_URBANO.nodes(data=True):
        if data.get("tipo") != "recoleccion":
            continue
        mat = data["material"]
        if req.material_preferido and req.material_preferido != "Todos" and mat != req.material_preferido:
            continue
        kg_disp = min(float(data["kg"]), max_kg * 0.6)
        tarifa = TARIFAS_BASE_MXN_KG.get(mat, 5.0) * float(data.get("demanda", 1.0))
        ingreso_nodo = round(kg_disp * tarifa, 2)
        dist_ida = nx.shortest_path_length(GRAFO_URBANO, "N0", node_id, weight="distancia_km")
        score = ingreso_nodo / max(dist_ida * cfg["factor_esfuerzo"], 0.2)
        candidatos.append((score, node_id, data, kg_disp, round(tarifa, 2), ingreso_nodo, round(dist_ida, 2)))

    candidatos.sort(reverse=True, key=lambda x: x[0])

    carga_acumulada = 0.0
    paradas = []
    orden = 1
    for _, node_id, data, kg_disp, tarifa, ingreso_nodo, dist_ida in candidatos:
        if carga_acumulada + kg_disp <= max_kg:
            carga_acumulada = round(carga_acumulada + kg_disp, 1)
            paradas.append({
                "orden": orden,
                "nodo": node_id,
                "lugar": data["nombre"],
                "tipo": "Recolección",
                "material": data["material"],
                "kg_estimados": kg_disp,
                "tarifa_mxn_kg": tarifa,
                "ingreso_estimado_mxn": ingreso_nodo,
                "distancia_desde_inicio_km": dist_ida,
            })
            orden += 1

    acopio_final = "A1" if (not paradas or paradas[-1]["material"] in ("PET", "Aluminio")) else "A2"
    acopio_data = GRAFO_URBANO.nodes[acopio_final]
    paradas.append({
        "orden": orden,
        "nodo": acopio_final,
        "lugar": acopio_data["nombre"],
        "tipo": "Centro de Acopio",
        "material": acopio_data["material"],
        "kg_estimados": carga_acumulada,
        "tarifa_mxn_kg": TARIFAS_BASE_MXN_KG.get(acopio_data["material"], 7.5),
        "ingreso_estimado_mxn": 0.0,
        "distancia_desde_inicio_km": round(nx.shortest_path_length(GRAFO_URBANO, "N0", acopio_final, weight="distancia_km"), 2),
    })

    distancia_total = 0.0
    prev = "N0"
    for p in paradas:
        actual = p["nodo"]
        if nx.has_path(GRAFO_URBANO, prev, actual):
            distancia_total += nx.shortest_path_length(GRAFO_URBANO, prev, actual, weight="distancia_km")
        else:
            distancia_total += 1.2
        prev = actual

    distancia_total = round(distancia_total, 2)
    distancia_sin_optimizar = round(distancia_total * 1.35, 2)
    km_ahorrados = round(max(distancia_sin_optimizar - distancia_total, 0.4), 2)
    ingreso_total = round(sum(p["ingreso_estimado_mxn"] for p in paradas), 2)
    co2_evitado = round(
        sum(p["kg_estimados"] * CO2_FACTOR_POR_KG.get(p["material"], 1.0) for p in paradas if p["tipo"] == "Recolección"),
        1,
    )

    explicacion = _generar_explicacion_gemini(vehiculo, paradas, distancia_total, km_ahorrados, carga_acumulada, ingreso_total)

    return {
        "vehiculo": vehiculo,
        "capacidad_max_kg": max_kg,
        "paradas": paradas,
        "metricas": {
            "distancia_total_km": distancia_total,
            "km_ahorrados": km_ahorrados,
            "kg_estimados": carga_acumulada,
            "ingreso_potencial_mxn": ingreso_total,
            "co2_evitado_kg": co2_evitado,
        },
        "explicacion_gemini": explicacion,
    }


def _generar_explicacion_gemini(vehiculo: str, paradas: list[dict], dist_km: float, km_ahorrados: float, kg: float, ingreso: float) -> str:
    resumen_fallback = (
        f"Con tu {vehiculo.lower()} aprovecharás mejor el viaje: recorrerás {dist_km} km, "
        f"ahorrarás cerca de {km_ahorrados} km, juntarás unos {kg} kg de material y podrías ganar "
        f"alrededor de ${ingreso:.2f} MXN pasando en orden por tus paradas hasta el centro de acopio."
    )
    if not gemini_client:
        return resumen_fallback

    prompt = (
        "Eres el copiloto de la app Rumbo para trabajadores recicladores en México. "
        "Explica esta ruta en 2 oraciones breves, cálidas y en español sencillo, sin tecnicismos ni listas:\n"
        f"Vehículo: {vehiculo}, Paradas: {[p['lugar'] for p in paradas]}, "
        f"Distancia: {dist_km} km, Ahorro: {km_ahorrados} km, Carga: {kg} kg, Ingreso estimado: ${ingreso:.2f} MXN."
    )
    try:
        resp = gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return (resp.text or "").strip() or resumen_fallback
    except Exception:
        return resumen_fallback


@app.post("/api/escaner/analizar")
async def analizar_residuo(
    imagen: UploadFile = File(...),
    material_pista: str = Form("PET"),
):
    contenido = await imagen.read()
    if not contenido:
        raise HTTPException(status_code=400, detail="No se recibió ninguna imagen.")

    fallback = {
        "material": material_pista if material_pista in TARIFAS_BASE_MXN_KG else "PET",
        "confianza": "95%",
        "estado_limpieza": "Separado y en buen estado",
        "tarifa_justa_mxn_kg": TARIFAS_BASE_MXN_KG.get(material_pista, 9.50),
        "acopio_recomendado": "Centro de Acopio Coacalco (Alta demanda)",
        "consejo": "Aplasta las botellas y quita tapas/etiquetas si es posible para ocupar menos espacio y mejorar la tarifa.",
    }

    if not gemini_client or not types:
        return fallback

    prompt = (
        "Analiza esta fotografía de material reciclable para un recolector urbano en México. "
        "Responde ÚNICAMENTE con un JSON válido con las llaves: "
        '{"material": "PET|Cartón|Aluminio|Vidrio|Chatarra", "confianza": "95%", '
        '"estado_limpieza": "...", "tarifa_justa_mxn_kg": 9.5, '
        '"acopio_recomendado": "...", "consejo": "..."}'
    )
    try:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=contenido, mime_type=imagen.content_type or "image/jpeg"),
                prompt,
            ],
        )
        texto = (resp.text or "").strip()
        if "```json" in texto:
            texto = texto.split("```json")[1].split("```")[0].strip()
        elif "```" in texto:
            texto = texto.split("```")[1].split("```")[0].strip()
        data = json.loads(texto)
        return {**fallback, **data}
    except Exception:
        return fallback


@app.get("/", response_class=HTMLResponse)
def vista_movil():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Rumbo · MVP</title>
  <style>
    :root { --verde: #1E6B52; --menta: #DDF0E4; --fondo: #F4F7F5; --texto: #111827; }
    body { font-family: system-ui, sans-serif; background: var(--fondo); color: var(--texto); margin: 0; padding: 16px; }
    .app { max-width: 440px; margin: 0 auto; background: #fff; border-radius: 20px; padding: 18px; box-shadow: 0 8px 24px rgba(0,0,0,.08); }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .badge { background: var(--menta); color: var(--verde); padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
    .card { background: var(--verde); color: #fff; border-radius: 16px; padding: 16px; margin-bottom: 14px; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
    .box { background: var(--fondo); border-radius: 12px; padding: 12px; }
    button { background: var(--verde); color: #fff; border: none; border-radius: 12px; padding: 12px 14px; font-weight: 600; width: 100%; cursor: pointer; margin-top: 8px; }
    button.sec { background: var(--menta); color: var(--verde); }
    select, input { width: 100%; padding: 10px; border-radius: 10px; border: 1px solid #cbd5e1; margin-top: 6px; box-sizing: border-box; }
    .parada { border-left: 4px solid var(--verde); background: var(--fondo); padding: 10px; border-radius: 8px; margin-bottom: 8px; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <div><strong>Rumbo</strong> · <span id="folioLbl">RMB-4821</span></div>
      <span class="badge" id="usuarioLbl">Caleb Silva</span>
    </div>

    <div class="card">
      <div style="font-size:13px;opacity:.9">Saldo disponible</div>
      <div style="font-size:28px;font-weight:800" id="saldoLbl">$245.00 MXN</div>
      <div style="font-size:12px;opacity:.9;margin-top:4px" id="impactoLbl">128 kg reciclados · 42 kg CO₂ evitado</div>
    </div>

    <div class="box" style="margin-bottom:14px">
      <strong>Credencial Virtual y Recuperación</strong>
      <div class="grid2" style="margin-top:8px;margin-bottom:6px">
        <input id="regNombre" placeholder="Nombre completo" />
        <input id="regColor" placeholder="Color favorito" />
      </div>
      <button class="sec" onclick="registrar()">Crear Usuario Virtual + PIN</button>
      <button class="sec" onclick="recuperar()">Recuperar con Nombre y Color</button>
      <div id="authMsg" style="font-size:12px;margin-top:8px;color:#1E6B52;font-weight:600"></div>
    </div>

    <div class="box" style="margin-bottom:14px">
      <strong>Ruta Óptima (Grafo)</strong>
      <select id="vehiculoSel">
        <option>A pie</option>
        <option>Diablito</option>
        <option selected>Triciclo</option>
        <option>Camioneta</option>
      </select>
      <button onclick="calcularRuta()">Calcular Ruta Óptima</button>
      <button class="sec" onclick="leerGuia()">Escuchar guía (voz)</button>
      <p id="guiaTxt" style="font-size:13px;background:#fff;padding:10px;border-radius:10px"></p>
      <div class="grid2" id="metricasBox"></div>
      <div id="paradasBox"></div>
    </div>

    <div class="box">
      <strong>Escáner Gemini (Foto de residuo)</strong>
      <input type="file" id="fotoInput" accept="image/*" />
      <button onclick="escanear()">Analizar Material con Gemini</button>
      <div id="scanRes" style="font-size:13px;margin-top:8px"></div>
    </div>
  </div>

  <script>
    async function registrar() {
      const nombre = document.getElementById("regNombre").value || "Recolector Nuevo";
      const color_favorito = document.getElementById("regColor").value || "verde";
      const vehiculo = document.getElementById("vehiculoSel").value;
      const res = await fetch("/api/auth/registro", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({nombre, color_favorito, vehiculo})
      });
      const data = await res.json();
      document.getElementById("folioLbl").innerText = data.folio;
      document.getElementById("usuarioLbl").innerText = data.perfil.nombre;
      document.getElementById("authMsg").innerText = `Usuario: ${data.folio} · PIN: ${data.pin}`;
    }

    async function recuperar() {
      const nombre = document.getElementById("regNombre").value;
      const color_favorito = document.getElementById("regColor").value;
      const res = await fetch("/api/auth/recuperar", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({nombre, color_favorito})
      });
      const data = await res.json();
      if (!res.ok) {
        document.getElementById("authMsg").innerText = data.detail || "No encontrado";
        return;
      }
      document.getElementById("folioLbl").innerText = data.folio;
      document.getElementById("usuarioLbl").innerText = data.perfil.nombre;
      document.getElementById("authMsg").innerText = `Recuperado · Folio: ${data.folio} · Nuevo PIN: ${data.nuevo_pin}`;
    }

    async function calcularRuta() {
      const vehiculo = document.getElementById("vehiculoSel").value;
      const res = await fetch("/api/ruta/calcular", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({vehiculo})
      });
      const data = await res.json();
      document.getElementById("guiaTxt").innerText = data.explicacion_gemini;
      const m = data.metricas;
      document.getElementById("metricasBox").innerHTML = `
        <div class="box"><strong>${m.km_ahorrados} km</strong><br><span style="font-size:12px">Ahorrados</span></div>
        <div class="box"><strong>${m.kg_estimados} kg</strong><br><span style="font-size:12px">Material est.</span></div>
        <div class="box"><strong>$${m.ingreso_potencial_mxn}</strong><br><span style="font-size:12px">Ingreso est.</span></div>
        <div class="box"><strong>${m.co2_evitado_kg} kg</strong><br><span style="font-size:12px">CO₂ evitado</span></div>
      `;
      document.getElementById("paradasBox").innerHTML = data.paradas.map(p => `
        <div class="parada">
          <strong>${p.orden}. ${p.lugar}</strong> (${p.tipo})<br>
          <span style="font-size:12px">${p.material} · ${p.kg_estimados} kg · $${p.tarifa_mxn_kg}/kg</span>
        </div>
      `).join("");
    }

    function leerGuia() {
      const txt = document.getElementById("guiaTxt").innerText;
      if (!txt || !("speechSynthesis" in window)) return;
      const utter = new SpeechSynthesisUtterance(txt);
      utter.lang = "es-MX";
      window.speechSynthesis.speak(utter);
    }

    async function escanear() {
      const inp = document.getElementById("fotoInput");
      if (!inp.files.length) {
        document.getElementById("scanRes").innerText = "Selecciona primero una foto.";
        return;
      }
      const fd = new FormData();
      fd.append("imagen", inp.files[0]);
      const res = await fetch("/api/escaner/analizar", {method: "POST", body: fd});
      const d = await res.json();
      document.getElementById("scanRes").innerHTML = `
        <strong>Material:</strong> ${d.material} (${d.confianza})<br>
        <strong>Estado:</strong> ${d.estado_limpieza}<br>
        <strong>Tarifa justa:</strong> $${d.tarifa_justa_mxn_kg} MXN/kg<br>
        <strong>Acopio:</strong> ${d.acopio_recomendado}<br>
        <strong>Tip:</strong> ${d.consejo}
      `;
    }

    calcularRuta();
  </script>
</body>
</html>"""