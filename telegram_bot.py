"""
Módulo del bot de Telegram.

No se conecta a la base de datos ni sabe nada de eBay: solo sabe enviar
mensajes a Telegram. El núcleo (worker) es quien detecta los artículos
nuevos y llama a las funciones de aquí pasándole los datos ya listos.
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _validar_config():
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. "
            "Revisa tu archivo .env (basado en .env.example)."
        )


def _post_con_reintento(url: str, data: dict, intentos_restantes: int = 2) -> requests.Response:
    """
    Envía la petición a Telegram. Si Telegram responde 429 (demasiadas
    peticiones), espera el tiempo que indique ('retry_after') y
    reintenta, hasta agotar los intentos.
    """
    resp = requests.post(url, data=data, timeout=10)

    if resp.status_code == 429 and intentos_restantes > 0:
        espera = resp.json().get("parameters", {}).get("retry_after", 3)
        time.sleep(espera + 0.5)
        return _post_con_reintento(url, data, intentos_restantes - 1)

    return resp


def enviar_mensaje_texto(texto: str) -> bool:
    """Envía un mensaje de texto simple. Devuelve True si se envió bien."""
    _validar_config()
    resp = _post_con_reintento(
        f"{API_URL}/sendMessage",
        {"chat_id": CHAT_ID, "text": texto, "parse_mode": "HTML"},
    )
    return resp.ok


def enviar_aviso_articulo_nuevo(articulo: dict) -> bool:
    """
    Envía el aviso de un artículo nuevo detectado.

    'articulo' debe incluir al menos: titulo, precio, url, tienda_nombre.
    Puede incluir opcionalmente: imagen_url, precio_oficial_mediamarkt.
    """
    _validar_config()

    titulo = articulo.get("titulo", "Artículo sin título")
    precio = articulo.get("precio")
    url = articulo.get("url", "")
    tienda = articulo.get("tienda_nombre", "")
    precio_oficial = articulo.get("precio_oficial_mediamarkt")

    texto = f"🆕 <b>{titulo}</b>\n"
    texto += f"🏬 Tienda: {tienda}\n"
    texto += f"💶 Precio eBay: {precio} €\n"

    if precio_oficial:
        diferencia = round(precio_oficial - precio, 2)
        texto += f"🏷️ Precio oficial MediaMarkt: {precio_oficial} €\n"
        if diferencia > 0:
            texto += f"✅ Ahorras {diferencia} € respecto al precio oficial\n"
        elif diferencia < 0:
            texto += f"⚠️ Está {abs(diferencia)} € más caro que el precio oficial\n"

    texto += f"\n🔗 {url}"

    imagen_url = articulo.get("imagen_url")
    if imagen_url:
        resp = _post_con_reintento(
            f"{API_URL}/sendPhoto",
            {
                "chat_id": CHAT_ID,
                "photo": imagen_url,
                "caption": texto,
                "parse_mode": "HTML",
            },
        )
        return resp.ok

    return enviar_mensaje_texto(texto)


if __name__ == "__main__":
    # Prueba manual: ejecuta "python telegram_bot.py" tras configurar el .env
    articulo_prueba = {
        "titulo": "Producto de prueba",
        "precio": 199.99,
        "url": "https://www.ebay.es/itm/000000000000",
        "tienda_nombre": "MediaMarkt Barcelona",
        "precio_oficial_mediamarkt": 229.99,
    }
    exito = enviar_aviso_articulo_nuevo(articulo_prueba)
    print("Mensaje enviado correctamente" if exito else "Fallo al enviar el mensaje")
