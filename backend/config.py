"""Configuración central de Fase 1.

Cambiar de fuente de datos (replay <-> live) debe ser solo tocar `SOURCE` aquí;
el consumidor (main.py) no cambia.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Carga backend/.env si existe (no se commitea). Las claves NO se hardcodean.
load_dotenv(Path(__file__).parent / ".env")

# --- Credenciales (desde .env) ---------------------------------------------
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")

# --- Watchlist y timeframe --------------------------------------------------
WATCHLIST = ["AMD", "NVDA"]   # extensible
TIMEFRAME = "1Min"             # timeframe inicial de Fase 1

# --- Hurst rolling (Fase 2) -------------------------------------------------
# Tamaño de la ventana de log-retornos para el DFA. Configurable: NO hay un H
# "verdadero" único, y NO se optimiza buscando estabilidad (eso sería sobreajuste).
HURST_WINDOW = 120

# Feed del plan gratuito: IEX explícito (no asumir el default).
FEED = "iex"

# --- Selección de fuente ----------------------------------------------------
# "replay" -> ReplaySource (histórico + reloj, determinista, corre a cualquier hora)
# "live"   -> LiveSource (WebSocket en tiempo real, solo en horario de mercado)
SOURCE = "live"

# --- Modo de suscripción para LiveSource ------------------------------------
# "A" (default): suscribirse a `bars` -> Alpaca entrega la vela de 1m ya agregada.
# "B" (preparado, no por defecto): suscribirse a `trades` y agregar a mano.
LIVE_MODE = "A"

# --- Parámetros de ReplaySource ---------------------------------------------
# Día de mercado a reproducir. Sesión normal reciente PERO de hace varios días
# (no hoy ni ayer), evitando fin de semana / festivo. Editable.
# 2026-06-20 es sábado -> usamos el lunes anterior, 2026-06-15.
REPLAY_DATE = "2026-06-17"

# Velocidad del reloj de replay:
#   1.0  -> tiempo real (1 barra de 1m cada 60 s)
#   10.0 -> 10x más rápido
#   0    -> instantáneo (sin esperas), útil para validar el flujo de un tirón
REPLAY_SPEED = 0.0

# Margen de seguridad para el feed gratuito IEX: los datos de los últimos 15 min
# están bloqueados. ReplaySource recorta el `end` para no rozar esa ventana.
RECENCY_MARGIN_MINUTES = 16
