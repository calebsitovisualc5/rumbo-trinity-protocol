# Rumbo — MVP (Trinity Protocol · UVM Hispano)

Aplicación web móvil enfocada en la inclusión financiera, digital y logística de trabajadores informales del reciclaje (Reto 3 · Ruta Digna, ODS 10 y 11).

## Equipo — Trinity Protocol (UVM Hispano)
- Caleb Genezareth Silva Guzmán
- Moisés Pacheco Ramos
- Sebastián Yahir Luna Martínez

## Funcionalidades reales implementadas en el MVP
- **Credencial Virtual y Recuperación sin fricción:** Generación automática de Usuario Virtual (`RMB-XXXX`) y PIN de 4 dígitos con saldo inicial en `$0.00 MXN` (`0.0 kg` reciclados), además de inicio de sesión por usuario o nombre y recuperación mediante Nombre completo y color favorito sin exigir teléfono, correo ni CURP.
- **Ruta Óptima sobre grafo urbano y mapa real:** Cálculo de ruta en Coacalco mediante grafo dirigido (`NetworkX`) y trazado vial real con `OpenStreetMap + Leaflet + OSRM`, adaptable a cuatro modos de transporte (`A pie`, `Diablito`, `Triciclo` y `Camioneta`) con estimación de distancia (km), tiempo (min), carga (kg) e ingreso potencial (`MXN`).
- **Escáner multimodal con Gemini 2.5 Flash:** Clasificación de residuos reciclables (`PET Limpio`, `Cartón`, `Aluminio`, `Cobre` y `HDPE`) a partir de fotografía subida o captura directa desde la cámara del dispositivo, mostrando porcentaje de confianza, tarifa justa por kilogramo, centro de acopio recomendado (`Centro Coacalco`), modo respaldo por defecto si no hay API Key configurada y lectura en voz alta (`Web Speech API`).
- **Cartera, Canje de Ganancias e Historial:** Registro directo de entregas que actualiza en tiempo real el saldo disponible, los kilogramos reciclados, el CO₂ evitado y el nivel del recolector (`Inicio`, `Plata`, `Oro`, `Esmeralda`), con opciones de canje (`Retiro de efectivo`, `Transferencia bancaria`, `Vale de despensa` y `Recarga de celular`) e historial persistente en JSON.
- **Asistente Gemini y Accesibilidad Visual:** Resumen personalizado con guía por voz en la sección *Mi perfil* y selector de **Modo oscuro** aplicado exclusivamente al marco móvil de la aplicación.

## Ejecución local
1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt

2.(Opcional) Configura tu clave de Gemini en un archivo .env o desde la sección Mi perfil dentro de la app (si no se ingresa, funciona en modo por defecto):
export GEMINI_API_KEY="tu_clave"

3. Inicia el servidor 
uvicorn app:app --reload --host 0.0.0.0 --port 8000

4. Abre en tu navegador: http://localhost:8000

Repositorio de código (GitHub): https://github.com/calebsitovisualc5/rumbo-trinity-protocol

Documentación y Boceto (Fase 2): https://docs.google.com/document/d/1sC9ldDKX93ltG_q9YxGcZk2rNqFqq2O2LJTkIH83eBg/edit
