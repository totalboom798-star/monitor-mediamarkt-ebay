"""
Módulo para consultar el precio de un producto en la web oficial de
mediamarkt.es.

Funciona en dos fases:
  1. buscar_url_producto(): usa un navegador automatizado (Playwright)
     solo para encontrar el enlace a la ficha del producto, porque la
     página de BÚSQUEDA de MediaMarkt carga los resultados con
     JavaScript.
  2. obtener_precio_producto(): una vez tenemos la URL de la ficha,
     esa página SÍ viene con el precio ya en el HTML inicial (lo
     comprobamos con un producto real), así que basta con una
     petición HTTP normal — mucho más rápida y ligera que abrir un
     navegador.
"""

import json
import re

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_SEARCH_URL = "https://www.mediamarkt.es/es/search.html?query="
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def buscar_url_producto(termino_busqueda: str, headless: bool = True) -> str | None:
    """
    Busca un término en mediamarkt.es y devuelve la URL de la ficha
    del primer producto encontrado, o None si no hay resultados.
    """
    url_busqueda = BASE_SEARCH_URL + termino_busqueda.replace(" ", "+")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        pagina = navegador.new_page()
        pagina.goto(url_busqueda, timeout=35000)

        try:
            # Las URLs de ficha de producto siguen siempre el patrón
            # /es/product/..., así que buscamos directamente un enlace
            # con esa forma en vez de depender de una clase CSS
            # concreta (más resistente a cambios de diseño).
            pagina.wait_for_selector("a[href*='/es/product/']", timeout=15000)
        except Exception:
            navegador.close()
            return None

        enlace = pagina.query_selector("a[href*='/es/product/']")
        href = enlace.get_attribute("href") if enlace else None
        navegador.close()

        if href and not href.startswith("http"):
            href = f"https://www.mediamarkt.es{href}"

        return href


def obtener_precio_producto(url_producto: str) -> dict:
    """
    Descarga la ficha de producto (petición HTTP normal, sin
    navegador) y extrae el precio.

    Devuelve: {"encontrado": bool, "precio": float|None, "titulo": str|None}
    """
    resultado = {"encontrado": False, "precio": None, "titulo": None}

    resp = requests.get(url_producto, headers=HEADERS, timeout=10)
    if not resp.ok:
        return resultado

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Intento 1: datos estructurados JSON-LD (schema.org Product) ---
    # Es el método más fiable si la web lo incluye, porque no depende
    # de clases CSS que puedan cambiar con el diseño.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            datos = json.loads(script.string)
        except (TypeError, ValueError):
            continue

        candidatos = datos if isinstance(datos, list) else [datos]
        for item in candidatos:
            if not isinstance(item, dict):
                continue
            oferta = item.get("offers")
            if isinstance(oferta, dict) and "price" in oferta:
                try:
                    resultado["precio"] = float(oferta["price"])
                    resultado["titulo"] = item.get("name")
                    resultado["encontrado"] = True
                    return resultado
                except (TypeError, ValueError):
                    pass

    # --- Intento 2 (respaldo): buscar un patrón de precio en el texto ---
    # Solo se usa si no había datos estructurados. Menos fiable, pero
    # sirve como red de seguridad.
    texto = soup.get_text(" ", strip=True)
    coincidencia = re.search(r"(\d{1,4}(?:[.,]\d{3})?[.,]\d{2})\s*€", texto)
    if coincidencia:
        precio_texto = coincidencia.group(1).replace(".", "").replace(",", ".")
        try:
            resultado["precio"] = float(precio_texto)
            resultado["encontrado"] = True
        except ValueError:
            pass

    titulo_tag = soup.find("h1")
    if titulo_tag:
        resultado["titulo"] = titulo_tag.get_text(strip=True)

    return resultado


def buscar_precio_mediamarkt(termino_busqueda: str, headless: bool = True) -> dict:
    """Función de conveniencia: hace las dos fases seguidas."""
    url = buscar_url_producto(termino_busqueda, headless=headless)
    if not url:
        return {"encontrado": False, "precio": None, "titulo": None, "url_producto": None}

    datos = obtener_precio_producto(url)
    datos["url_producto"] = url
    return datos


if __name__ == "__main__":
    termino = "iphone 15 128gb negro"
    print(f"Buscando: {termino}")
    resultado = buscar_precio_mediamarkt(termino, headless=False)
    print(resultado)

