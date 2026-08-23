"""
Gestión de un ÚNICO navegador (Playwright) compartido por todo el
programa.

Playwright no permite tener varias sesiones "sync_playwright()"
abiertas a la vez en el mismo proceso — si ebay_client.py y
mediamarkt_scraper.py abren cada uno la suya por separado, se produce
el error "It looks like you are using Playwright Sync API inside the
asyncio loop" (y a veces incluso hace que las páginas "crasheen").

Por eso el navegador se abre UNA SOLA VEZ aquí, y el resto de módulos
piden pestañas nuevas a partir de este mismo navegador en vez de
lanzar cada uno el suyo.
"""

from playwright.sync_api import sync_playwright

_playwright_instancia = None
_navegador = None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def iniciar():
    """Abre el navegador compartido. Seguro de llamar aunque ya esté abierto."""
    global _playwright_instancia, _navegador
    if _navegador is not None:
        return

    _playwright_instancia = sync_playwright().start()
    _navegador = _playwright_instancia.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )


def nueva_pagina():
    """Abre una pestaña nueva dentro del navegador compartido."""
    if _navegador is None:
        raise RuntimeError(
            "El navegador compartido no está iniciado. Llama a iniciar() primero "
            "(esto se hace una vez al principio de nucleo.py)."
        )

    contexto = _navegador.new_context(
        user_agent=USER_AGENT,
        locale="es-ES",
        viewport={"width": 1280, "height": 800},
        extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
    )
    contexto.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return contexto.new_page()


def cerrar():
    """Cierra el navegador compartido. Llamar al terminar el programa."""
    global _playwright_instancia, _navegador
    if _navegador:
        _navegador.close()
    if _playwright_instancia:
        _playwright_instancia.stop()
    _navegador = None
    _playwright_instancia = None
