import base64
import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "rumbo_data.json"
ENV_FILE = BASE_DIR / ".env"
LOGO_FILE = BASE_DIR / "logorumbo.png"


def _load_local_env() -> None:
    if ENV_FILE.exists():
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass


_load_local_env()
RUNTIME_GEMINI_KEY: Optional[str] = None

VEHICLE_CONFIG: Dict[str, Dict[str, Any]] = {
    "A pie": {
        "speed_kmh": 4.2,
        "savings_factor": 0.18,
        "capacity_factor": 0.35,
        "rate_per_kg": 9.50,
        "osrm_profile": "foot",
        "route_title": "1. Punto Norte · PET · $9.50/kg",
        "acopio_line": "2. Acopio Coacalco · 1.2 km",
    },
    "Diablito": {
        "speed_kmh": 6.5,
        "savings_factor": 0.28,
        "capacity_factor": 0.65,
        "rate_per_kg": 10.20,
        "osrm_profile": "foot",
        "route_title": "1. Punto Norte · PET / Cartón · $10.20/kg",
        "acopio_line": "2. Acopio Coacalco · 1.2 km",
    },
    "Triciclo": {
        "speed_kmh": 11.0,
        "savings_factor": 0.35,
        "capacity_factor": 1.00,
        "rate_per_kg": 11.97,
        "osrm_profile": "bicycle",
        "route_title": "1. Punto Norte · PET · $9.50/kg",
        "acopio_line": "2. Acopio Coacalco · 1.2 km",
    },
    "Camioneta": {
        "speed_kmh": 22.0,
        "savings_factor": 0.35,
        "capacity_factor": 1.45,
        "rate_per_kg": 12.60,
        "osrm_profile": "driving",
        "route_title": "1. Punto Norte · Carga mixta · $12.60/kg",
        "acopio_line": "2. Acopio Coacalco · 1.2 km",
    },
}

MATERIAL_RATES: Dict[str, Dict[str, Any]] = {
    "PET Limpio": {
        "price_per_kg": 9.50,
        "co2_per_kg": 1.50,
        "acopio": "Centro Coacalco (Alta demanda)",
        "confidence": "96%",
    },
    "Cartón": {
        "price_per_kg": 4.20,
        "co2_per_kg": 0.90,
        "acopio": "Centro Coacalco (Alta demanda)",
        "confidence": "94%",
    },
    "Aluminio": {
        "price_per_kg": 26.00,
        "co2_per_kg": 9.10,
        "acopio": "Centro Coacalco (Alta demanda)",
        "confidence": "95%",
    },
    "Cobre": {
        "price_per_kg": 135.00,
        "co2_per_kg": 3.40,
        "acopio": "Centro Coacalco (Alta demanda)",
        "confidence": "93%",
    },
    "HDPE": {
        "price_per_kg": 8.00,
        "co2_per_kg": 1.30,
        "acopio": "Centro Coacalco (Alta demanda)",
        "confidence": "92%",
    },
}

app = FastAPI(title="Rumbo · Trinity Protocol")


class RegisterRequest(BaseModel):
    assigned_username: str = Field(..., min_length=4, max_length=20)
    full_name: str = Field(..., min_length=2, max_length=100)
    favorite_color: str = Field(..., min_length=2, max_length=50)
    pin: str = Field(..., min_length=4, max_length=4)


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=2, max_length=100)
    pin: str = Field(..., min_length=4, max_length=4)


class RecoverRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    favorite_color: str = Field(..., min_length=2, max_length=50)


class RouteRequest(BaseModel):
    username: str
    vehicle: str = "Triciclo"


class CompletePickupRequest(BaseModel):
    username: str
    material: str
    weight_kg: float = Field(..., gt=0, le=2000)
    source: str = "Registro de material"


class RedeemRequest(BaseModel):
    username: str
    method: str
    amount_mxn: float = Field(..., gt=0)


class ScanRequest(BaseModel):
    username: Optional[str] = None
    image_base64: str
    mime_type: str = "image/jpeg"
    estimated_kg: float = Field(default=1.5, gt=0, le=500)


class GeminiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=250)


class AssistantRequest(BaseModel):
    username: str
    prompt: Optional[str] = None


def get_gemini_key() -> str:
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    return (RUNTIME_GEMINI_KEY or "").strip()


def _default_store() -> Dict[str, Any]:
    return {"users": {}}


def load_store() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        data = _default_store()
        save_store(data)
        return data
    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "users" not in data:
            return _default_store()
        return data
    except Exception:
        return _default_store()


def save_store(data: Dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp_file.replace(DATA_FILE)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _generate_username(existing_users: Dict[str, Any]) -> str:
    for _ in range(500):
        code = f"RMB-{random.randint(1000, 9999)}"
        if code not in existing_users:
            return code
    raise HTTPException(status_code=500, detail="No fue posible generar un usuario disponible.")


def _level_from_kg(recycled_kg: float) -> str:
    if recycled_kg >= 100:
        return "Esmeralda"
    if recycled_kg >= 30:
        return "Oro"
    if recycled_kg >= 5:
        return "Plata"
    return "Inicio"


def _sanitize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    recycled_kg = round(float(user.get("recycled_kg", 0.0)), 2)
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "favorite_color": user["favorite_color"],
        "balance_mxn": round(float(user.get("balance_mxn", 0.0)), 2),
        "recycled_kg": recycled_kg,
        "co2_avoided_kg": round(float(user.get("co2_avoided_kg", 0.0)), 2),
        "level_name": _level_from_kg(recycled_kg),
        "history": user.get("history", [])[-20:],
    }


def _find_user_by_identifier(users: Dict[str, Any], identifier: str) -> Optional[Dict[str, Any]]:
    raw_upper = identifier.strip().upper()
    if raw_upper in users:
        return users[raw_upper]

    norm_name = _normalize_text(identifier)
    matches = [u for u in users.values() if _normalize_text(u.get("full_name", "")) == norm_name]
    if matches:
        return matches[-1]
    return None


def build_logistics_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    nodes = {
        "Inicio": {"label": "Base del recolector · Coacalco", "material_kg": 0.0, "lat": 19.6335, "lng": -99.1045},
        "P1": {"label": "1. Punto Norte · PET · $9.50/kg", "material_kg": 14.0, "lat": 19.6412, "lng": -99.1010},
        "P2": {"label": "2. Calle Norte · Cartón", "material_kg": 18.5, "lat": 19.6378, "lng": -99.0955},
        "P3": {"label": "3. Mercado Local · Aluminio", "material_kg": 16.5, "lat": 19.6310, "lng": -99.0920},
        "Acopio": {"label": "Acopio Coacalco · Entrega final", "material_kg": 0.0, "lat": 19.6275, "lng": -99.1018},
    }
    for node_id, meta in nodes.items():
        graph.add_node(node_id, **meta)

    edges: List[Tuple[str, str, float]] = [
        ("Inicio", "P1", 1.2),
        ("Inicio", "P2", 2.1),
        ("P1", "P2", 1.4),
        ("P1", "P3", 1.9),
        ("P2", "P3", 1.3),
        ("P2", "Acopio", 1.7),
        ("P3", "Acopio", 1.2),
        ("P1", "Acopio", 1.2),
    ]
    for src, dst, dist_km in edges:
        graph.add_edge(src, dst, weight=dist_km)
    return graph


def compute_route_plan(vehicle: str) -> Dict[str, Any]:
    cfg = VEHICLE_CONFIG.get(vehicle, VEHICLE_CONFIG["Triciclo"])
    graph = build_logistics_graph()

    ordered_stops = ["Inicio", "P1", "P2", "P3", "Acopio"]
    total_km = 0.0
    for idx in range(len(ordered_stops) - 1):
        u, v = ordered_stops[idx], ordered_stops[idx + 1]
        if graph.has_edge(u, v):
            total_km += float(graph[u][v]["weight"])
        else:
            total_km += float(nx.shortest_path_length(graph, source=u, target=v, weight="weight"))

    saved_km = round(total_km * cfg["savings_factor"], 2)
    base_kg = sum(float(graph.nodes[n].get("material_kg", 0.0)) for n in ["P1", "P2", "P3"])
    estimated_kg = round(base_kg * cfg["capacity_factor"], 1)
    estimated_earnings_mxn = round(estimated_kg * cfg["rate_per_kg"], 2)
    estimated_minutes = max(8, int(round((total_km / cfg["speed_kmh"]) * 60)))

    waypoints_coords = [
        {
            "id": n,
            "label": graph.nodes[n]["label"],
            "lat": graph.nodes[n]["lat"],
            "lng": graph.nodes[n]["lng"],
        }
        for n in ordered_stops
    ]

    return {
        "vehicle": vehicle,
        "osrm_profile": cfg["osrm_profile"],
        "speed_kmh": cfg["speed_kmh"],
        "headline_stop": cfg["route_title"],
        "acopio_stop": cfg["acopio_line"],
        "stops": [graph.nodes[n]["label"] for n in ordered_stops],
        "waypoints": waypoints_coords,
        "total_km": round(total_km, 2),
        "saved_km": saved_km,
        "estimated_kg": estimated_kg,
        "estimated_earnings_mxn": estimated_earnings_mxn,
        "estimated_minutes": estimated_minutes,
    }


def _default_gemini_scan(estimated_kg: float) -> Dict[str, Any]:
    material = "PET Limpio"
    rates = MATERIAL_RATES[material]
    return {
        "material": material,
        "confidence": rates["confidence"],
        "rate_per_kg": rates["price_per_kg"],
        "acopio": rates["acopio"],
        "estimated_weight_kg": round(estimated_kg, 2),
        "estimated_value_mxn": round(estimated_kg * rates["price_per_kg"], 2),
        "co2_avoided_kg": round(estimated_kg * rates["co2_per_kg"], 2),
        "engine": "Gemini (modo por defecto)",
    }


def analyze_with_gemini(image_base64: str, mime_type: str, estimated_kg: float) -> Dict[str, Any]:
    api_key = get_gemini_key()
    if not api_key or genai is None or types is None:
        return _default_gemini_scan(estimated_kg)

    clean_b64 = image_base64.split(",")[-1].strip()
    try:
        raw_bytes = base64.b64decode(clean_b64, validate=True)
    except Exception:
        return _default_gemini_scan(estimated_kg)

    prompt = (
        "Clasifica el material reciclable en esta imagen para la app Rumbo. "
        "Responde ÚNICAMENTE con un objeto JSON válido con las llaves: "
        "material (uno de: PET Limpio, Cartón, Aluminio, Cobre, HDPE), "
        "confidence (porcentaje entre 88% y 99%), "
        "acopio (texto breve en español)."
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=raw_bytes, mime_type=mime_type or "image/jpeg"),
                prompt,
            ],
        )
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        mat = parsed.get("material", "PET Limpio")
        if mat not in MATERIAL_RATES:
            mat = "PET Limpio"
        rates = MATERIAL_RATES[mat]
        return {
            "material": mat,
            "confidence": str(parsed.get("confidence", rates["confidence"])),
            "rate_per_kg": rates["price_per_kg"],
            "acopio": str(parsed.get("acopio", rates["acopio"])),
            "estimated_weight_kg": round(estimated_kg, 2),
            "estimated_value_mxn": round(estimated_kg * rates["price_per_kg"], 2),
            "co2_avoided_kg": round(estimated_kg * rates["co2_per_kg"], 2),
            "engine": "Gemini 2.5 Flash",
        }
    except Exception:
        return _default_gemini_scan(estimated_kg)


@app.get("/logorumbo.png")
def get_logo_rumbo() -> FileResponse:
    if not LOGO_FILE.exists():
        raise HTTPException(status_code=404, detail="No se encontró logorumbo.png junto a app.py.")
    return FileResponse(path=LOGO_FILE, media_type="image/png")


@app.get("/api/status")
def api_status() -> Dict[str, Any]:
    return {
        "gemini_active": True,
        "live_api_key": bool(get_gemini_key()),
        "map_provider": "OpenStreetMap + Leaflet + OSRM (Gratuito)",
    }


@app.get("/api/auth/next-username")
def get_next_username() -> Dict[str, str]:
    store = load_store()
    return {"username": _generate_username(store["users"])}


@app.post("/api/config/gemini-key")
def set_gemini_key(payload: GeminiKeyRequest) -> Dict[str, Any]:
    global RUNTIME_GEMINI_KEY
    key = payload.api_key.strip()
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="Clave de Gemini no válida.")
    RUNTIME_GEMINI_KEY = key
    os.environ["GEMINI_API_KEY"] = key
    return {"gemini_active": True, "live_api_key": True, "message": "Clave de Gemini vinculada."}


@app.post("/api/auth/register")
def register_user(payload: RegisterRequest) -> Dict[str, Any]:
    pin_clean = payload.pin.strip()
    if not (pin_clean.isdigit() and len(pin_clean) == 4):
        raise HTTPException(status_code=400, detail="El PIN debe tener exactamente 4 dígitos.")

    assigned_code = payload.assigned_username.strip().upper()
    if not (assigned_code.startswith("RMB-") and len(assigned_code) == 8 and assigned_code[4:].isdigit()):
        raise HTTPException(
            status_code=400,
            detail="Debes ingresar el Usuario asignado por la app (formato RMB-XXXX).",
        )

    store = load_store()
    if assigned_code in store["users"]:
        raise HTTPException(
            status_code=409,
            detail=f"El usuario {assigned_code} ya está registrado. Inicia sesión o solicita uno nuevo.",
        )

    clean_name = " ".join(payload.full_name.strip().split())
    user_record = {
        "username": assigned_code,
        "full_name": clean_name,
        "favorite_color": payload.favorite_color.strip(),
        "pin": pin_clean,
        "balance_mxn": 0.0,
        "recycled_kg": 0.0,
        "co2_avoided_kg": 0.0,
        "history": [],
    }
    store["users"][assigned_code] = user_record
    save_store(store)
    return {"user": _sanitize_user(user_record)}


@app.post("/api/auth/login")
def login_user(payload: LoginRequest) -> Dict[str, Any]:
    identifier = payload.identifier.strip()
    pin_clean = payload.pin.strip()
    store = load_store()
    user = _find_user_by_identifier(store["users"], identifier)
    if not user or str(user.get("pin", "")).strip() != pin_clean:
        raise HTTPException(status_code=401, detail="Usuario, nombre o PIN incorrectos.")
    return {"user": _sanitize_user(user)}


@app.post("/api/auth/recover")
def recover_user(payload: RecoverRequest) -> Dict[str, Any]:
    target_name = _normalize_text(payload.full_name)
    target_color = _normalize_text(payload.favorite_color)
    store = load_store()
    for user in store["users"].values():
        if (
            _normalize_text(user.get("full_name", "")) == target_name
            and _normalize_text(user.get("favorite_color", "")) == target_color
        ):
            return {"username": user["username"], "pin": user["pin"], "user": _sanitize_user(user)}
    raise HTTPException(status_code=404, detail="No encontramos una cuenta con ese nombre y color favorito.")


@app.post("/api/route")
def calculate_route(payload: RouteRequest) -> Dict[str, Any]:
    store = load_store()
    if payload.username.strip().upper() not in store["users"]:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if payload.vehicle not in VEHICLE_CONFIG:
        raise HTTPException(status_code=400, detail="Vehículo no válido.")
    return compute_route_plan(payload.vehicle)


@app.post("/api/pickups/complete")
def complete_pickup(payload: CompletePickupRequest) -> Dict[str, Any]:
    username = payload.username.strip().upper()
    material = payload.material.strip()
    if material not in MATERIAL_RATES:
        raise HTTPException(status_code=400, detail="Material no válido.")

    store = load_store()
    user = store["users"].get(username)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    rates = MATERIAL_RATES[material]
    weight = round(float(payload.weight_kg), 2)
    earned_mxn = round(weight * rates["price_per_kg"], 2)
    co2_kg = round(weight * rates["co2_per_kg"], 2)

    user["balance_mxn"] = round(float(user.get("balance_mxn", 0.0)) + earned_mxn, 2)
    user["recycled_kg"] = round(float(user.get("recycled_kg", 0.0)) + weight, 2)
    user["co2_avoided_kg"] = round(float(user.get("co2_avoided_kg", 0.0)) + co2_kg, 2)

    entry = {
        "source": payload.source,
        "material": material,
        "weight_kg": weight,
        "earned_mxn": earned_mxn,
        "co2_avoided_kg": co2_kg,
    }
    history = user.get("history", [])
    history.append(entry)
    user["history"] = history[-25:]
    save_store(store)

    return {"earned_mxn": earned_mxn, "entry": entry, "user": _sanitize_user(user)}


@app.post("/api/redeem")
def redeem_balance(payload: RedeemRequest) -> Dict[str, Any]:
    username = payload.username.strip().upper()
    store = load_store()
    user = store["users"].get(username)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    current_bal = round(float(user.get("balance_mxn", 0.0)), 2)
    amount = round(float(payload.amount_mxn), 2)
    if amount <= 0 or amount > current_bal:
        raise HTTPException(
            status_code=400,
            detail=f"Saldo insuficiente. Tu saldo disponible real es de ${current_bal:.2f} MXN.",
        )

    user["balance_mxn"] = round(current_bal - amount, 2)
    history = user.get("history", [])
    history.append(
        {
            "source": f"Canje · {payload.method}",
            "material": "Retiro / Canje",
            "weight_kg": 0.0,
            "earned_mxn": -amount,
            "co2_avoided_kg": 0.0,
        }
    )
    user["history"] = history[-25:]
    save_store(store)
    return {"redeemed_mxn": amount, "method": payload.method, "user": _sanitize_user(user)}


@app.post("/api/scan")
def scan_material(payload: ScanRequest) -> Dict[str, Any]:
    return analyze_with_gemini(
        image_base64=payload.image_base64,
        mime_type=payload.mime_type,
        estimated_kg=payload.estimated_kg,
    )


@app.post("/api/assistant")
def assistant_guidance(payload: AssistantRequest) -> Dict[str, Any]:
    store = load_store()
    user = store["users"].get(payload.username.strip().upper())
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    bal = float(user.get("balance_mxn", 0.0))
    kg = float(user.get("recycled_kg", 0.0))
    co2 = float(user.get("co2_avoided_kg", 0.0))
    first_name = user["full_name"].split()[0]

    default_text = (
        f"Hola {first_name}, llevas ${bal:.2f} MXN acumulados, {kg:.1f} kg reciclados "
        f"y {co2:.1f} kg de CO2 evitado. Puedes revisar la Ruta Óptima en Triciclo o escanear "
        f"material limpio como PET para sumar a tu saldo en Acopio Coacalco."
    )

    api_key = get_gemini_key()
    if not api_key or genai is None:
        return {"text": default_text, "engine": "Gemini (modo por defecto)"}

    try:
        client = genai.Client(api_key=api_key)
        question = payload.prompt or "Dame un resumen breve y práctico de mi avance y siguiente paso en Rumbo."
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"Eres el asistente de voz de la app Rumbo (reciclaje y logística). "
                f"Usuario: {user['full_name']} ({user['username']}), saldo: ${bal:.2f} MXN, "
                f"kg reciclados: {kg:.1f}, CO2 evitado: {co2:.1f} kg. "
                f"Responde en español en máximo 2 oraciones claras: {question}"
            ),
        )
        out = (resp.text or "").strip() or default_text
        return {"text": out, "engine": "Gemini 2.5 Flash"}
    except Exception:
        return {"text": default_text, "engine": "Gemini (modo por defecto)"}


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Rumbo · Recolecta, recicla y gana</title>
  <link rel="icon" href="data:," />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    :root {
      --bg: #e7ece9;
      --phone-bg: #f6faf7;
      --card: #ffffff;
      --ink: #111827;
      --muted: #52606d;
      --line: #d6e2da;
      --green: #14532d;
      --green-mid: #166534;
      --green-soft: #dcfce7;
      --green-wash: #eaf6ee;
      --danger-bg: #fef2f2;
      --danger-tx: #991b1b;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      padding: 18px 10px 32px;
    }

    .phone-frame {
      width: 100%;
      max-width: 410px;
      min-height: 760px;
      background: var(--phone-bg);
      border-radius: 36px;
      border: 8px solid var(--ink);
      box-shadow: 0 20px 50px rgba(17, 24, 39, 0.16);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
    }

    /* Modo oscuro aplicado exclusivamente al marco del celular (.phone-frame) */
    .phone-frame.dark-mode {
      background: #0f1713;
      color: #ecfdf5;
      border-color: #050806;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35);
    }
    .phone-frame.dark-mode .status-bar {
      color: #ecfdf5;
    }
    .phone-frame.dark-mode .screen-title,
    .phone-frame.dark-mode .welcome-title,
    .phone-frame.dark-mode .credential-line,
    .phone-frame.dark-mode .stat-num,
    .phone-frame.dark-mode label {
      color: #ecfdf5;
    }
    .phone-frame.dark-mode .welcome-sub,
    .phone-frame.dark-mode .stat-lbl {
      color: #9fb3a8;
    }
    .phone-frame.dark-mode .card-panel,
    .phone-frame.dark-mode .route-stop-card,
    .phone-frame.dark-mode .stat-box,
    .phone-frame.dark-mode .option-row,
    .phone-frame.dark-mode .veh-btn,
    .phone-frame.dark-mode .back-btn,
    .phone-frame.dark-mode .btn-secondary {
      background: #16221c;
      color: #ecfdf5;
      border-color: #26382f;
    }
    .phone-frame.dark-mode .veh-btn.active {
      background: #22c55e;
      color: #07130c;
      border-color: #22c55e;
    }
    .phone-frame.dark-mode .credential-preview,
    .phone-frame.dark-mode .quick-tile {
      background: #172920;
      color: #ecfdf5;
      border-color: #26382f;
    }
    .phone-frame.dark-mode .quick-icon {
      background: #101b15;
      color: #4ade80;
      border-color: #26382f;
    }
    .phone-frame.dark-mode .promo-banner,
    .phone-frame.dark-mode .verified-badge {
      background: #142c1e;
      color: #86efac;
    }
    .phone-frame.dark-mode .btn-soft {
      background: #1b3828;
      color: #86efac;
    }
    .phone-frame.dark-mode input,
    .phone-frame.dark-mode select {
      background: #101b15;
      color: #ecfdf5;
      border-color: #2c4036;
    }
    .phone-frame.dark-mode .bottom-nav {
      background: #131e18;
      border-top-color: #26382f;
    }
    .phone-frame.dark-mode .nav-btn {
      color: #94a89e;
    }
    .phone-frame.dark-mode .nav-btn.active {
      color: #4ade80;
    }
    .phone-frame.dark-mode .avatar-circle {
      background: #1f3d2c;
      color: #ecfdf5;
    }
    .phone-frame.dark-mode .link-btn {
      color: #9fb3a8;
    }

    .status-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 20px 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--ink);
    }

    .screen {
      flex: 1;
      padding: 10px 18px 86px;
      overflow-y: auto;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 14px;
    }

    .topbar-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .back-btn {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--ink);
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
      display: grid;
      place-items: center;
    }

    .screen-title {
      margin: 0;
      font-size: 18px;
      font-weight: 800;
      color: var(--ink);
    }

    .welcome-box {
      text-align: center;
      padding: 18px 4px 10px;
    }

    .rumbo-mark {
      width: 144px;
      height: 144px;
      margin: 0 auto 12px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .rumbo-mark img {
      max-width: 144px;
      max-height: 144px;
      width: auto;
      height: auto;
      object-fit: contain;
      border-radius: 22px;
      display: block;
    }

    .welcome-title {
      margin: 24px 0 0;
      font-size: 32px;
      font-weight: 900;
      letter-spacing: -0.6px;
      color: var(--ink);
    }

    .welcome-sub {
      margin: 6px 0 24px;
      font-size: 14px;
      color: var(--muted);
    }

    .credential-preview {
      background: var(--green-wash);
      border: 1.5px solid #86efac;
      border-radius: 16px;
      padding: 14px 16px;
      text-align: left;
      margin-bottom: 20px;
    }

    .credential-line {
      font-size: 15px;
      font-weight: 800;
      color: var(--ink);
      margin: 2px 0 4px;
    }

    .btn {
      width: 100%;
      border: none;
      border-radius: 16px;
      padding: 13px 16px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }

    .btn-primary {
      background: var(--green);
      color: #ffffff;
    }

    .btn-secondary {
      background: var(--card);
      color: var(--ink);
      border: 1.5px solid var(--line);
      margin-top: 12px;
    }

    .btn-dark {
      background: var(--ink);
      color: #ffffff;
    }

    .btn-soft {
      background: var(--green-soft);
      color: var(--green);
      padding: 8px 12px;
      border-radius: 12px;
      font-size: 12.5px;
      font-weight: 700;
      border: none;
      cursor: pointer;
    }

    .link-btn {
      background: none;
      border: none;
      color: var(--muted);
      font-size: 12px;
      text-decoration: underline;
      cursor: pointer;
      margin-top: 16px;
    }

    .home-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 14px;
    }

    .avatar-circle {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: var(--ink);
      color: #ffffff;
      display: grid;
      place-items: center;
      font-weight: 800;
      font-size: 16px;
    }

    .verified-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: var(--green-soft);
      color: var(--green);
      font-size: 11.5px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 999px;
      margin-top: 3px;
    }

    .balance-card {
      background: linear-gradient(135deg, var(--ink) 0%, var(--green) 100%);
      color: #ffffff;
      border-radius: 20px;
      padding: 18px;
      cursor: pointer;
      margin-bottom: 14px;
    }

    .balance-card-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      opacity: 0.92;
    }

    .balance-big {
      font-size: 30px;
      font-weight: 900;
      margin-top: 6px;
    }

    .quick-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 14px;
    }

    .quick-tile {
      background: var(--green-wash);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px 12px;
      text-align: center;
      cursor: pointer;
      color: var(--ink);
      font-weight: 700;
      font-size: 13.5px;
    }

    .quick-icon {
      width: 38px;
      height: 38px;
      margin: 0 auto 8px;
      border-radius: 12px;
      background: var(--card);
      color: var(--green);
      display: grid;
      place-items: center;
      font-size: 18px;
      font-weight: 800;
      border: 1px solid var(--line);
    }

    .promo-banner {
      background: var(--green-soft);
      border-radius: 16px;
      padding: 12px 14px;
      font-size: 13.5px;
      font-weight: 700;
      color: var(--green);
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .vehicle-bar {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }

    .veh-btn {
      background: var(--card);
      border: 1.5px solid var(--line);
      border-radius: 14px;
      padding: 8px 4px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--ink);
      cursor: pointer;
      text-align: center;
    }

    .veh-btn.active {
      background: var(--ink);
      color: #ffffff;
      border-color: var(--ink);
    }

    .map-box {
      background: #eef4ef;
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      margin-bottom: 12px;
      height: 205px;
      position: relative;
      z-index: 1;
    }

    #osm-map {
      width: 100%;
      height: 100%;
    }

    .rumbo-pin {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #14532d;
      color: #ffffff;
      border: 2px solid #ffffff;
      box-shadow: 0 2px 6px rgba(17, 24, 39, 0.35);
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 800;
    }

    .rumbo-pin.start {
      background: #2563eb;
    }

    .rumbo-pin.end {
      background: #111827;
    }

    .route-stop-card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      margin-bottom: 12px;
      font-size: 13.5px;
      line-height: 1.45;
    }

    .scanner-frame {
      background: var(--ink);
      border-radius: 18px;
      padding: 14px;
      color: #ffffff;
      margin-bottom: 12px;
      min-height: 190px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .scan-overlay-pill {
      background: rgba(17, 24, 39, 0.88);
      border: 1px solid #4ade80;
      color: #ffffff;
      border-radius: 12px;
      padding: 8px 12px;
      font-size: 12.5px;
      font-weight: 700;
      margin-top: 8px;
    }

    .option-row {
      width: 100%;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 15px;
      padding: 13px 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
      cursor: pointer;
      margin-bottom: 9px;
      text-align: left;
    }

    .stats-3 {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 12px 0;
    }

    .stat-box {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 8px;
      text-align: center;
    }

    .stat-num {
      font-size: 14px;
      font-weight: 800;
      color: var(--ink);
    }

    .stat-lbl {
      font-size: 11px;
      color: var(--muted);
      margin-top: 2px;
    }

    .card-panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 13px 14px;
      margin-bottom: 11px;
    }

    label {
      display: block;
      font-size: 12px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 4px;
    }

    input, select {
      width: 100%;
      padding: 9px 11px;
      border-radius: 11px;
      border: 1px solid var(--line);
      font-size: 13.5px;
      background: #ffffff;
      color: var(--ink);
      margin-bottom: 9px;
    }

    .msg {
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 12.5px;
      line-height: 1.4;
      margin-top: 8px;
    }

    .msg-ok {
      background: var(--green-soft);
      color: var(--green);
      font-weight: 600;
    }

    .msg-err {
      background: var(--danger-bg);
      color: var(--danger-tx);
      font-weight: 600;
    }

    .bottom-nav {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      background: var(--card);
      border-top: 1px solid var(--line);
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      padding: 8px 6px 10px;
      z-index: 20;
    }

    .nav-btn {
      background: none;
      border: none;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }

    .nav-btn.active {
      color: var(--green);
    }

    .hidden { display: none !important; }
  </style>
</head>
<body>
  <div class="phone-frame" id="phone-frame">
    <div class="status-bar">
      <span>9:41</span>
      <span id="gemini-pill" style="font-size: 10.5px; color: var(--green);">Gemini por defecto</span>
    </div>

    <!-- PANTALLA 1: BIENVENIDA Y ACCESO -->
    <div id="view-welcome" class="screen">
      <div class="welcome-box">
        <div class="rumbo-mark" aria-hidden="true">
          <img src="/logorumbo.png" alt="Logo Rumbo" />
        </div>
        <h1 class="welcome-title">Rumbo</h1>
        <p class="welcome-sub">Recolecta, recicla y gana</p>

        <div class="credential-preview">
          <div class="credential-line">Usuario asignado: <span id="preview-user">RMB-8177</span></div>
          <div style="font-size: 11.5px; color: var(--muted); margin-top: 4px;">
            Saldo inicial al registrarte: <strong>$0.00 MXN</strong> (0.0 kg reciclados)
          </div>
        </div>

        <button id="btn-go-register" type="button" class="btn btn-primary">Comenzar &nbsp;&rsaquo;</button>
        <button id="btn-go-login" type="button" class="btn btn-secondary">Iniciar sesión</button>

        <button id="btn-go-recover" type="button" class="link-btn">
          ¿Olvidaste tu contraseña?
        </button>
      </div>

      <form id="form-register" class="card-panel hidden" style="margin-top: 12px;">
        <h3 style="margin: 0 0 8px; font-size: 15px;">Crear Credencial</h3>
        <label for="reg-assigned-user">Usuario asignado por la app (obligatorio)</label>
        <input id="reg-assigned-user" type="text" placeholder="RMB-XXXX" required />
        <label for="reg-name">Nombre completo (obligatorio)</label>
        <input id="reg-name" type="text" placeholder="Tu nombre" required />
        <label for="reg-color">Color favorito</label>
        <input id="reg-color" type="text" placeholder="Color" required />
        <label for="reg-pin">Elige tu PIN de 4 dígitos</label>
        <input id="reg-pin" type="password" inputmode="numeric" maxlength="4" placeholder="Ej. 0000" required />
        <button type="submit" class="btn btn-primary">Crear Cuenta</button>
      </form>

      <form id="form-login" class="card-panel hidden" style="margin-top: 12px;">
        <h3 style="margin: 0 0 8px; font-size: 15px;">Iniciar sesión</h3>
        <label for="login-identifier">Usuario (RMB-XXXX) o Tu nombre</label>
        <input id="login-identifier" type="text" placeholder="RMB-XXXX o Tu nombre" required />
        <label for="login-pin">PIN de 4 dígitos</label>
        <input id="login-pin" type="password" inputmode="numeric" maxlength="4" placeholder="Ej. 0000" required />
        <button type="submit" class="btn btn-dark">Entrar</button>
      </form>

      <form id="form-recover" class="card-panel hidden" style="margin-top: 12px;">
        <h3 style="margin: 0 0 8px; font-size: 15px;">Recuperar con Nombre y Color</h3>
        <label for="rec-name">Nombre completo</label>
        <input id="rec-name" type="text" placeholder="Tu nombre" required />
        <label for="rec-color">Color favorito</label>
        <input id="rec-color" type="text" placeholder="Color" required />
        <button type="submit" class="btn btn-dark">Recuperar usuario y PIN</button>
      </form>

      <div id="auth-feedback" class="msg hidden"></div>
    </div>

    <!-- PANTALLA 2: INICIO -->
    <div id="view-home" class="screen hidden">
      <div class="home-header">
        <div class="topbar-left">
          <div class="avatar-circle" id="home-avatar">RB</div>
          <div>
            <div style="font-size: 17px; font-weight: 800;" id="home-greeting">Hola</div>
            <div class="verified-badge">&#10003; Recolector verificado</div>
          </div>
        </div>
        <button id="home-bell" type="button" class="back-btn" title="Estado de cuenta">&#128276;</button>
      </div>

      <div id="home-saldo-card" class="balance-card">
        <div class="balance-card-top">
          <span>&#128091; Tu saldo</span>
          <span>&rsaquo;</span>
        </div>
        <div class="balance-big" id="home-balance">$ 0.00 MXN</div>
      </div>

      <div class="quick-grid">
        <button id="tile-registrar" type="button" class="quick-tile">
          <div class="quick-icon">+</div>
          Registrar material
        </button>
        <button id="tile-ruta" type="button" class="quick-tile">
          <div class="quick-icon">&#128205;</div>
          Ruta Óptima
        </button>
        <button id="tile-canjear" type="button" class="quick-tile">
          <div class="quick-icon">&#128176;</div>
          Canjear ganancias
        </button>
        <button id="tile-historial" type="button" class="quick-tile">
          <div class="quick-icon">&#128202;</div>
          Historial
        </button>
      </div>

      <div class="promo-banner">
        <span>&#9851;</span>
        <span>Recicla hoy, mejora tu ingreso</span>
      </div>

      <div id="home-notice" class="msg msg-ok hidden"></div>
    </div>

    <!-- PANTALLA 3: RUTA ÓPTIMA (OPENSTREETMAP + OSRM GRATIS) -->
    <div id="view-ruta" class="screen hidden">
      <div class="topbar">
        <div class="topbar-left">
          <button type="button" class="back-btn" data-back="home">&lsaquo;</button>
          <h2 class="screen-title">Ruta Óptima</h2>
        </div>
      </div>

      <div class="vehicle-bar" id="vehicle-bar">
        <button type="button" class="veh-btn" data-veh="A pie">&#128694;<br/>A pie</button>
        <button type="button" class="veh-btn" data-veh="Diablito">&#128722;<br/>Diablito</button>
        <button type="button" class="veh-btn active" data-veh="Triciclo">&#128690;<br/>Triciclo</button>
        <button type="button" class="veh-btn" data-veh="Camioneta">&#128666;<br/>Camioneta</button>
      </div>

      <div class="map-box">
        <div id="osm-map"></div>
      </div>

      <div class="route-stop-card">
        <div id="route-stop-1" style="font-weight: 800;">1. Punto Norte · PET · $9.50/kg</div>
        <div id="route-stop-2" style="font-weight: 700; color: var(--green); margin-top: 2px;">2. Acopio Coacalco · 1.2 km</div>
        <div id="route-meta-line" style="font-size: 12px; color: var(--muted); margin-top: 6px;"></div>
      </div>

      <button id="btn-start-route" type="button" class="btn btn-primary">Iniciar Ruta</button>
      <div id="route-feedback" class="msg msg-ok hidden"></div>
    </div>

    <!-- PANTALLA 4: ESCÁNER GEMINI -->
    <div id="view-escaner" class="screen hidden">
      <div class="topbar">
        <div class="topbar-left">
          <button type="button" class="back-btn" data-back="home">&lsaquo;</button>
          <h2 class="screen-title">Escáner Gemini</h2>
        </div>
        <button id="btn-toggle-cam" type="button" class="btn-soft">&#128247; Cámara</button>
      </div>

      <div class="scanner-frame">
        <img id="scan-preview-img" alt="Vista previa del material" style="width: 100%; max-height: 155px; object-fit: cover; border-radius: 12px; display: none;" />
        <video id="scan-video" autoplay playsinline style="width: 100%; max-height: 155px; object-fit: cover; border-radius: 12px; display: none;"></video>
        <button id="btn-capture-photo" type="button" class="btn btn-primary hidden" style="margin-top: 8px; padding: 9px 12px; font-size: 13.5px;">
          &#128248; Tomar foto
        </button>
        <div id="scan-placeholder" style="text-align: center; padding: 24px 8px; font-size: 13px; color: #d1fae5;">
          Sube una foto o abre la cámara para clasificar el material con Gemini
        </div>

        <div class="scan-overlay-pill">
          &#10024; Material: <span id="scan-mat-label">PET Limpio</span> · <span id="scan-conf-label">96%</span>
        </div>
        <div class="scan-overlay-pill" style="background: var(--green); border-color: #bbf7d0;">
          &#128178; Tarifa justa: <span id="scan-rate-label">$9.50 / kg</span>
        </div>
      </div>

      <div class="card-panel">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
          <div>
            <div style="font-size: 11.5px; color: var(--muted);">Mejor acopio:</div>
            <div id="scan-acopio" style="font-size: 13.5px; font-weight: 800;">Centro Coacalco (Alta demanda)</div>
          </div>
          <button id="btn-speak-scan" type="button" class="btn-soft">&#128266; Escuchar</button>
        </div>

        <div style="margin-top: 10px;">
          <label for="scan-file">Elegir fotografía</label>
          <input id="scan-file" type="file" accept="image/*" />
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            <div>
              <label for="scan-mat-select">Material a registrar</label>
              <select id="scan-mat-select">
                <option value="PET Limpio" selected>PET Limpio ($9.50/kg)</option>
                <option value="Cartón">Cartón ($4.20/kg)</option>
                <option value="Aluminio">Aluminio ($26.00/kg)</option>
                <option value="Cobre">Cobre ($135.00/kg)</option>
                <option value="HDPE">HDPE ($8.00/kg)</option>
              </select>
            </div>
            <div>
              <label for="scan-kg-input">Peso (kg)</label>
              <input id="scan-kg-input" type="number" step="0.1" min="0.1" value="1.5" />
            </div>
          </div>
        </div>
      </div>

      <button id="btn-register-material" type="button" class="btn btn-primary">Registrar material</button>
      <div id="scan-feedback" class="msg msg-ok hidden"></div>
    </div>

    <!-- PANTALLA 5: CANJEAR GANANCIAS -->
    <div id="view-canjear" class="screen hidden">
      <div class="topbar">
        <div class="topbar-left">
          <button type="button" class="back-btn" data-back="home">&lsaquo;</button>
          <h2 class="screen-title">Canjear ganancias</h2>
        </div>
      </div>

      <div class="balance-card" style="cursor: default;">
        <div class="balance-card-top">
          <span>&#128091; Saldo disponible</span>
          <span>&rsaquo;</span>
        </div>
        <div class="balance-big" id="redeem-balance">$ 0.00 MXN</div>
      </div>

      <div style="font-size: 13px; font-weight: 700; color: var(--muted); margin-bottom: 8px;">Elige una opción</div>

      <button type="button" class="option-row" data-method="Retiro de efectivo">
        <span>&#128181; Retiro de efectivo</span>
        <span>&rsaquo;</span>
      </button>
      <button type="button" class="option-row" data-method="Transferencia bancaria">
        <span>&#127974; Transferencia bancaria</span>
        <span>&rsaquo;</span>
      </button>
      <button type="button" class="option-row" data-method="Vale de despensa">
        <span>&#127873; Vale de despensa</span>
        <span>&rsaquo;</span>
      </button>
      <button type="button" class="option-row" data-method="Recarga de celular">
        <span>&#128241; Recarga de celular</span>
        <span>&rsaquo;</span>
      </button>

      <form id="form-redeem" class="card-panel hidden">
        <div id="redeem-method-title" style="font-weight: 800; margin-bottom: 8px;"></div>
        <label for="redeem-amount">Monto a canjear (MXN)</label>
        <input id="redeem-amount" type="number" step="0.01" min="1" placeholder="Ej. 50.00" required />
        <button type="submit" class="btn btn-dark">Confirmar canje</button>
      </form>

      <div id="redeem-feedback" class="msg hidden"></div>
    </div>

    <!-- PANTALLA 6: MI PERFIL + ASISTENTE GEMINI + HISTORIAL -->
    <div id="view-perfil" class="screen hidden">
      <div class="topbar">
        <div class="topbar-left">
          <button type="button" class="back-btn" data-back="home">&lsaquo;</button>
          <h2 class="screen-title">Mi perfil</h2>
        </div>
      </div>

      <div style="text-align: center; margin-bottom: 10px;">
        <div class="avatar-circle" style="width: 66px; height: 66px; font-size: 24px; margin: 0 auto 8px;" id="profile-avatar">RB</div>
        <div style="font-size: 18px; font-weight: 900;" id="profile-name">Operador</div>
        <div style="font-size: 12.5px; color: var(--muted);">Folio <span id="profile-folio">RMB-8177</span></div>
        <div class="verified-badge">&#10003; Recolector verificado</div>
      </div>

      <div class="stats-3">
        <div class="stat-box">
          <div class="stat-num" id="stat-kg">0 kg</div>
          <div class="stat-lbl">Reciclados</div>
        </div>
        <div class="stat-box">
          <div class="stat-num" id="stat-co2">0 kg</div>
          <div class="stat-lbl">CO&#8322; evitado</div>
        </div>
        <div class="stat-box">
          <div class="stat-num" id="stat-level">Inicio</div>
          <div class="stat-lbl">Nivel</div>
        </div>
      </div>

      <div class="card-panel" style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
        <div>
          <div style="font-weight: 800; font-size: 13.5px;">&#127769; Modo oscuro</div>
          <div style="font-size: 11.5px; color: var(--muted);"></div>
        </div>
        <button id="btn-toggle-phone-dark" type="button" class="btn-soft">Desactivado</button>
      </div>

      <div class="card-panel" style="background: var(--green-wash);">
        <div style="font-weight: 800; font-size: 14px;">&#10024; Asistente Gemini</div>
        <div id="assistant-text" style="font-size: 12.5px; color: var(--muted); margin: 4px 0 8px;">
          Te explico tu avance y rutas en voz alta
        </div>
        <button id="btn-assistant-voice" type="button" class="btn-soft">&#128266; Escuchar guía</button>
      </div>

      <div class="card-panel">
        <label for="gemini-key-input">Clave GEMINI_API_KEY (opcional para IA en vivo)</label>
        <div style="display: flex; gap: 8px;">
          <input id="gemini-key-input" type="password" placeholder="AIza..." style="margin-bottom: 0;" />
          <button id="btn-save-key" type="button" class="btn-soft" style="white-space: nowrap;">Guardar</button>
        </div>
        <div id="key-feedback" class="msg msg-ok hidden"></div>
      </div>

      <button id="btn-show-recovery-info" type="button" class="option-row">
        <span>&#128273; Recuperación: Nombre y Color</span>
        <span>&rsaquo;</span>
      </button>

      <div id="history-panel" class="card-panel">
        <div style="font-weight: 800; font-size: 13.5px; margin-bottom: 6px;">Historial reciente</div>
        <div id="profile-history" style="font-size: 12.5px; color: var(--muted);">Sin movimientos registrados aún.</div>
      </div>

      <button id="btn-logout" type="button" class="option-row" style="color: var(--danger-tx);">
        <span>&#10162; Cerrar sesión</span>
        <span>&rsaquo;</span>
      </button>
    </div>

    <!-- BARRA INFERIOR -->
    <nav id="bottom-nav" class="bottom-nav hidden" aria-label="Navegación principal">
      <button type="button" class="nav-btn active" data-nav="home">&#127968;<span>Inicio</span></button>
      <button type="button" class="nav-btn" data-nav="escaner">&#128247;<span>Escáner</span></button>
      <button type="button" class="nav-btn" data-nav="ruta">&#128205;<span>Ruta</span></button>
      <button type="button" class="nav-btn" data-nav="perfil">&#128100;<span>Perfil</span></button>
    </nav>
  </div>

  <script>
    let currentUser = null;
    let assignedCode = "RMB-8177";
    let selectedVehicle = "Triciclo";
    let selectedRedeemMethod = "";
    let lastScanText = "Material PET Limpio, tarifa justa de 9.50 pesos por kilogramo, centro de acopio en Coacalco.";
    let cameraStream = null;
    let osmMap = null;
    let osmMarkersLayer = null;
    let osmRouteLine = null;
    let latestRoutePlan = null;

    const views = {
      welcome: document.getElementById("view-welcome"),
      home: document.getElementById("view-home"),
      ruta: document.getElementById("view-ruta"),
      escaner: document.getElementById("view-escaner"),
      canjear: document.getElementById("view-canjear"),
      perfil: document.getElementById("view-perfil"),
    };

    function stopCamera() {
      if (cameraStream) {
        cameraStream.getTracks().forEach((t) => t.stop());
        cameraStream = null;
      }
      document.getElementById("scan-video").style.display = "none";
      document.getElementById("btn-capture-photo").classList.add("hidden");
    }

    function showScreen(name) {
      stopCamera();
      Object.entries(views).forEach(([k, el]) => el.classList.toggle("hidden", k !== name));
      const nav = document.getElementById("bottom-nav");
      nav.classList.toggle("hidden", name === "welcome");
      document.querySelectorAll(".nav-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.nav === name);
      });
      if (name === "ruta" && currentUser) {
        initOsmMap();
        setTimeout(() => {
          if (osmMap) osmMap.invalidateSize();
          loadRoute(selectedVehicle);
        }, 60);
      }
      if (name === "perfil" && currentUser) {
        loadAssistantSummary();
      }
    }

    function initOsmMap() {
      if (osmMap || typeof window.L === "undefined") return;
      osmMap = window.L.map("osm-map", {
        center: [19.6345, -99.1005],
        zoom: 14,
        zoomControl: true,
      });
      window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap",
      }).addTo(osmMap);
      osmMarkersLayer = window.L.layerGroup().addTo(osmMap);
    }

    async function drawRouteOnOsmMap(plan) {
      initOsmMap();
      if (!osmMap || !plan || !Array.isArray(plan.waypoints) || plan.waypoints.length < 2) return;

      osmMarkersLayer.clearLayers();
      if (osmRouteLine) {
        osmMap.removeLayer(osmRouteLine);
        osmRouteLine = null;
      }

      const latLngs = [];
      plan.waypoints.forEach((wp, idx) => {
        const isStart = idx === 0;
        const isEnd = idx === plan.waypoints.length - 1;
        const cls = isStart ? "rumbo-pin start" : isEnd ? "rumbo-pin end" : "rumbo-pin";
        const icon = window.L.divIcon({
          className: "",
          html: `<div class="${cls}">${idx + 1}</div>`,
          iconSize: [24, 24],
          iconAnchor: [12, 12],
        });
        window.L.marker([wp.lat, wp.lng], { icon })
          .bindPopup(`<strong>${wp.label}</strong>`)
          .addTo(osmMarkersLayer);
        latLngs.push([wp.lat, wp.lng]);
      });

      const coordStr = plan.waypoints.map((wp) => `${wp.lng},${wp.lat}`).join(";");
      const profile = plan.osrm_profile || "bicycle";
      const osrmUrl = `[https://router.project-osrm.org/route/v1/$](https://router.project-osrm.org/route/v1/$){profile}/${coordStr}?overview=full&geometries=geojson`;

      try {
        const resp = await fetch(osrmUrl);
        const data = await resp.json();
        const route = data?.routes?.[0];
        if (route?.geometry?.coordinates?.length) {
          const streetCoords = route.geometry.coordinates.map(([lng, lat]) => [lat, lng]);
          osmRouteLine = window.L.polyline(streetCoords, {
            color: "#166534",
            weight: 4.5,
            opacity: 0.92,
          }).addTo(osmMap);
          osmMap.fitBounds(osmRouteLine.getBounds(), { padding: [22, 22] });

          const distKm = (Number(route.distance) / 1000).toFixed(2);
          const speed = Number(plan.speed_kmh) || 11.0;
          const mins = Math.max(6, Math.round((Number(distKm) / speed) * 60));
          document.getElementById("route-meta-line").textContent =
            `Ruta real: ${distKm} km · ~${mins} min · Carga est. ${plan.estimated_kg} kg (~$${plan.estimated_earnings_mxn} MXN)`;
          return;
        }
      } catch (_) {}

      osmRouteLine = window.L.polyline(latLngs, {
        color: "#166534",
        weight: 4,
        dashArray: "6 5",
      }).addTo(osmMap);
      osmMap.fitBounds(osmRouteLine.getBounds(), { padding: [22, 22] });
    }

    function speakText(text) {
      if (!("speechSynthesis" in window)) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "es-MX";
      window.speechSynthesis.speak(u);
    }

    function renderUser(user) {
      currentUser = user;
      const parts = user.full_name.trim().split(/\\s+/);
      const initials = ((parts[0]?.[0] || "R") + (parts[1]?.[0] || "")).toUpperCase();
      const firstName = parts[0] || user.username;
      const balStr = `$ ${Number(user.balance_mxn).toFixed(2)} MXN`;

      document.getElementById("home-avatar").textContent = initials;
      document.getElementById("home-greeting").textContent = `Hola, ${firstName}`;
      document.getElementById("home-balance").textContent = balStr;
      document.getElementById("redeem-balance").textContent = balStr;

      document.getElementById("profile-avatar").textContent = initials;
      document.getElementById("profile-name").textContent = user.full_name;
      document.getElementById("profile-folio").textContent = user.username;
      document.getElementById("stat-kg").textContent = `${Number(user.recycled_kg).toFixed(0)} kg`;
      document.getElementById("stat-co2").textContent = `${Number(user.co2_avoided_kg).toFixed(0)} kg`;
      document.getElementById("stat-level").textContent = user.level_name || "Inicio";

      const histEl = document.getElementById("profile-history");
      if (!user.history || user.history.length === 0) {
        histEl.textContent = "Sin movimientos registrados aún. Tu saldo inició en $0.00 MXN.";
      } else {
        histEl.innerHTML = [...user.history]
          .reverse()
          .slice(0, 6)
          .map((h) => {
            const sign = Number(h.earned_mxn) >= 0 ? "+" : "";
            return `<div style="padding:6px 0; border-bottom:1px solid var(--line); display:flex; justify-content:space-between;">
              <span><strong>${h.material}</strong> (${Number(h.weight_kg).toFixed(1)} kg)</span>
              <span><strong>${sign}$${Number(h.earned_mxn).toFixed(2)}</strong></span>
            </div>`;
          })
          .join("");
      }
    }

    function showAuthFeedback(text, isErr = false) {
      const box = document.getElementById("auth-feedback");
      box.textContent = text;
      box.className = "msg " + (isErr ? "msg-err" : "msg-ok");
      box.classList.remove("hidden");
    }

    function openAuthForm(mode) {
      document.getElementById("form-register").classList.toggle("hidden", mode !== "register");
      document.getElementById("form-login").classList.toggle("hidden", mode !== "login");
      document.getElementById("form-recover").classList.toggle("hidden", mode !== "recover");
      document.getElementById("auth-feedback").classList.add("hidden");
    }

    async function refreshAssignedUsername() {
      try {
        const res = await fetch("/api/auth/next-username");
        if (res.ok) {
          const data = await res.json();
          assignedCode = data.username;
          document.getElementById("preview-user").textContent = assignedCode;
          document.getElementById("reg-assigned-user").value = assignedCode;
        }
      } catch (_) {}
    }

    document.getElementById("btn-go-register").addEventListener("click", async () => {
      await refreshAssignedUsername();
      openAuthForm("register");
    });

    document.getElementById("btn-go-login").addEventListener("click", () => {
      openAuthForm("login");
    });

    document.getElementById("btn-go-recover").addEventListener("click", () => openAuthForm("recover"));

    document.getElementById("form-register").addEventListener("submit", async (e) => {
      e.preventDefault();
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          assigned_username: document.getElementById("reg-assigned-user").value,
          full_name: document.getElementById("reg-name").value,
          favorite_color: document.getElementById("reg-color").value,
          pin: document.getElementById("reg-pin").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) return showAuthFeedback(data.detail || "Error al registrar.", true);
      renderUser(data.user);
      showScreen("home");
    });

    document.getElementById("form-login").addEventListener("submit", async (e) => {
      e.preventDefault();
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: document.getElementById("login-identifier").value,
          pin: document.getElementById("login-pin").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) return showAuthFeedback(data.detail || "Credenciales inválidas.", true);
      renderUser(data.user);
      showScreen("home");
    });

    document.getElementById("form-recover").addEventListener("submit", async (e) => {
      e.preventDefault();
      const res = await fetch("/api/auth/recover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: document.getElementById("rec-name").value,
          favorite_color: document.getElementById("rec-color").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) return showAuthFeedback(data.detail || "No se encontró cuenta.", true);
      document.getElementById("login-identifier").value = data.username;
      showAuthFeedback(`Recuperado: Usuario ${data.username} · PIN ${data.pin}`);
    });

    document.querySelectorAll("[data-back]").forEach((b) => {
      b.addEventListener("click", () => showScreen(b.dataset.back));
    });
    document.querySelectorAll("[data-nav]").forEach((b) => {
      b.addEventListener("click", () => showScreen(b.dataset.nav));
    });

    document.getElementById("tile-registrar").addEventListener("click", () => showScreen("escaner"));
    document.getElementById("tile-ruta").addEventListener("click", () => showScreen("ruta"));
    document.getElementById("tile-canjear").addEventListener("click", () => showScreen("canjear"));
    document.getElementById("tile-historial").addEventListener("click", () => showScreen("perfil"));
    document.getElementById("home-saldo-card").addEventListener("click", () => showScreen("canjear"));
    document.getElementById("home-bell").addEventListener("click", () => {
      if (!currentUser) return;
      const n = document.getElementById("home-notice");
      n.textContent = `Usuario ${currentUser.username}: saldo real de $${Number(currentUser.balance_mxn).toFixed(2)} MXN.`;
      n.classList.remove("hidden");
    });

    async function loadRoute(vehicle) {
      selectedVehicle = vehicle;
      document.querySelectorAll(".veh-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.veh === vehicle);
      });
      const res = await fetch("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: currentUser.username, vehicle }),
      });
      const data = await res.json();
      if (!res.ok) return;
      latestRoutePlan = data;
      document.getElementById("route-stop-1").textContent = data.headline_stop;
      document.getElementById("route-stop-2").textContent = data.acopio_stop;
      document.getElementById("route-meta-line").textContent =
        `${data.total_km} km · ~${data.estimated_minutes} min · Carga est. ${data.estimated_kg} kg (~$${data.estimated_earnings_mxn} MXN)`;
      drawRouteOnOsmMap(data);
    }

    document.querySelectorAll(".veh-btn").forEach((btn) => {
      btn.addEventListener("click", () => loadRoute(btn.dataset.veh));
    });

    document.getElementById("btn-start-route").addEventListener("click", () => {
      const fb = document.getElementById("route-feedback");
      fb.textContent = `Ruta iniciada en ${selectedVehicle}. Al completar la entrega, regístrala en Escáner para sumar a tu saldo.`;
      fb.classList.remove("hidden");
      if (latestRoutePlan) drawRouteOnOsmMap(latestRoutePlan);
    });

    document.getElementById("btn-toggle-cam").addEventListener("click", async () => {
      const video = document.getElementById("scan-video");
      const placeholder = document.getElementById("scan-placeholder");
      const captureBtn = document.getElementById("btn-capture-photo");
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
      try {
        cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.srcObject = cameraStream;
        video.style.display = "block";
        document.getElementById("scan-preview-img").style.display = "none";
        placeholder.style.display = "none";
        captureBtn.classList.remove("hidden");
      } catch (_) {
        captureBtn.classList.add("hidden");
        placeholder.textContent = "Cámara no disponible en este navegador; usa 'Elegir fotografía'.";
      }
    });

    document.getElementById("btn-capture-photo").addEventListener("click", () => {
      const video = document.getElementById("scan-video");
      if (!cameraStream || !video.videoWidth || !video.videoHeight) return;
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
      const img = document.getElementById("scan-preview-img");
      img.src = dataUrl;
      img.style.display = "block";
      stopCamera();
      runScan(dataUrl, "image/jpeg");
    });

    async function runScan(base64Data, mimeType) {
      const estKg = parseFloat(document.getElementById("scan-kg-input").value) || 1.5;
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: currentUser ? currentUser.username : null,
          image_base64: base64Data,
          mime_type: mimeType || "image/jpeg",
          estimated_kg: estKg,
        }),
      });
      const data = await res.json();
      if (!res.ok) return;
      document.getElementById("scan-mat-label").textContent = data.material;
      document.getElementById("scan-conf-label").textContent = data.confidence;
      document.getElementById("scan-rate-label").textContent = `$${Number(data.rate_per_kg).toFixed(2)} / kg`;
      document.getElementById("scan-acopio").textContent = data.acopio;
      const sel = document.getElementById("scan-mat-select");
      if ([...sel.options].some((o) => o.value === data.material)) {
        sel.value = data.material;
      }
      lastScanText = `Material ${data.material}, tarifa justa de ${Number(data.rate_per_kg).toFixed(2)} pesos por kilogramo en ${data.acopio}.`;
      const fb = document.getElementById("scan-feedback");
      fb.textContent = `Análisis (${data.engine}): ${data.material} · Estimado $${Number(data.estimated_value_mxn).toFixed(2)} MXN por ${Number(data.estimated_weight_kg).toFixed(1)} kg.`;
      fb.className = "msg msg-ok";
      fb.classList.remove("hidden");
    }

    document.getElementById("scan-file").addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      stopCamera();
      const reader = new FileReader();
      reader.onload = () => {
        const img = document.getElementById("scan-preview-img");
        img.src = reader.result;
        img.style.display = "block";
        document.getElementById("scan-placeholder").style.display = "none";
        runScan(reader.result, file.type);
      };
      reader.readAsDataURL(file);
    });

    document.getElementById("btn-speak-scan").addEventListener("click", () => speakText(lastScanText));

    document.getElementById("btn-register-material").addEventListener("click", async () => {
      if (!currentUser) return;
      const material = document.getElementById("scan-mat-select").value;
      const weightKg = parseFloat(document.getElementById("scan-kg-input").value);
      const res = await fetch("/api/pickups/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: currentUser.username,
          material,
          weight_kg: weightKg,
          source: "Escáner / Acopio Coacalco",
        }),
      });
      const data = await res.json();
      const fb = document.getElementById("scan-feedback");
      if (!res.ok) {
        fb.textContent = data.detail || "No se pudo registrar el material.";
        fb.className = "msg msg-err";
        fb.classList.remove("hidden");
        return;
      }
      renderUser(data.user);
      fb.textContent = `Registrado: +$${Number(data.earned_mxn).toFixed(2)} MXN sumados a tu saldo.`;
      fb.className = "msg msg-ok";
      fb.classList.remove("hidden");
    });

    document.querySelectorAll("[data-method]").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedRedeemMethod = btn.dataset.method;
        document.getElementById("redeem-method-title").textContent = selectedRedeemMethod;
        document.getElementById("form-redeem").classList.remove("hidden");
        document.getElementById("redeem-feedback").classList.add("hidden");
      });
    });

    document.getElementById("form-redeem").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!currentUser) return;
      const amount = parseFloat(document.getElementById("redeem-amount").value);
      const res = await fetch("/api/redeem", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: currentUser.username,
          method: selectedRedeemMethod,
          amount_mxn: amount,
        }),
      });
      const data = await res.json();
      const fb = document.getElementById("redeem-feedback");
      if (!res.ok) {
        fb.textContent = data.detail || "No se pudo realizar el canje.";
        fb.className = "msg msg-err";
        fb.classList.remove("hidden");
        return;
      }
      renderUser(data.user);
      fb.textContent = `Canje aplicado (${selectedRedeemMethod}): -$${Number(data.redeemed_mxn).toFixed(2)} MXN.`;
      fb.className = "msg msg-ok";
      fb.classList.remove("hidden");
    });

    document.getElementById("btn-toggle-phone-dark").addEventListener("click", () => {
      const frame = document.getElementById("phone-frame");
      const btn = document.getElementById("btn-toggle-phone-dark");
      const enabled = frame.classList.toggle("dark-mode");
      btn.textContent = enabled ? "Activado" : "Desactivado";
    });

    async function loadAssistantSummary() {
      if (!currentUser) return;
      const res = await fetch("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: currentUser.username }),
      });
      const data = await res.json();
      if (res.ok && data.text) {
        document.getElementById("assistant-text").textContent = data.text;
      }
    }

    document.getElementById("btn-assistant-voice").addEventListener("click", () => {
      speakText(document.getElementById("assistant-text").textContent);
    });

    document.getElementById("btn-save-key").addEventListener("click", async () => {
      const apiKey = document.getElementById("gemini-key-input").value.trim();
      const res = await fetch("/api/config/gemini-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await res.json();
      const fb = document.getElementById("key-feedback");
      if (!res.ok) {
        fb.textContent = data.detail || "Clave inválida.";
        fb.className = "msg msg-err";
        fb.classList.remove("hidden");
        return;
      }
      document.getElementById("gemini-pill").textContent = "Gemini activo";
      fb.textContent = data.message;
      fb.className = "msg msg-ok";
      fb.classList.remove("hidden");
      loadAssistantSummary();
    });

    document.getElementById("btn-show-recovery-info").addEventListener("click", () => {
      if (!currentUser) return;
      alert(`Nombre: ${currentUser.full_name}\\nColor favorito: ${currentUser.favorite_color}\\nUsuario: ${currentUser.username}`);
    });

    document.getElementById("btn-logout").addEventListener("click", async () => {
      currentUser = null;
      localStorage.removeItem("rumbo_active_user");
      await refreshAssignedUsername();
      showScreen("welcome");
    });

    async function initApp() {
      localStorage.removeItem("rumbo_active_user");
      try {
        const st = await fetch("/api/status").then((r) => r.json());
        document.getElementById("gemini-pill").textContent = st.live_api_key ? "Gemini activo" : "Gemini por defecto";
      } catch (_) {}
      await refreshAssignedUsername();
      showScreen("welcome");
    }

    initApp();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=HTML_PAGE)