# Rumbo — MVP (Trinity Protocol · UVM Hispano)

Aplicación móvil enfocada en la inclusión de trabajadores informales del reciclaje (Reto 3 · Ruta Digna, ODS 10 y 11).

## Equipo — Trinity Protocol (UVM Hispano)
* Caleb Genezareth Silva Guzmán
* Moisés Pacheco Ramos
* Sebastián Yahir Luna Martínez

## Funcionalidades del MVP
* **Credencial Virtual y Recuperación**: Registro que genera Usuario Virtual (`RMB-XXXX`) y PIN de 4 dígitos, más recuperación por **Nombre completo y color favorito** sin exigir teléfono ni correo.
* **Ruta óptima sobre grafo urbano**: Cálculo de paradas y centros de acopio según vehículo (*A pie, Diablito, Triciclo, Camioneta*), capacidad de carga, distancia y tarifa.
* **Escáner multimodal con Gemini**: Clasificación de residuos a partir de foto, tarifa justa estimada, acopio recomendado y explicación en lenguaje claro (con lectura en voz alta).
* **Reporte de impacto**: Kilómetros ahorrados, kilogramos estimados, ingreso potencial y CO2 evitado.

## Ejecución local
1. Instala dependencias: `pip install -r requirements.txt`
2. Configura tu variable de entorno: `export GEMINI_API_KEY="tu_clave"`
3. Ejecuta: `uvicorn app:app --reload --host 0.0.0.0 --port 8000`

## Enlaces del proyecto
* **Documentación y Boceto (Fase 2)**: https://docs.google.com/document/d/1sC9ldDKX93ltG_q9YxGcZk2rNqFqq2O2LJTkIH83eBg/edit
* **Aplicación demostrable (APK / Demo)**: `[PENDIENTE DE AGREGAR ANTES DE LAS 18:30 H]`
