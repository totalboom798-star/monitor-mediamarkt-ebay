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

import navegador_compartido

BASE_SEARCH_URL = "https://www.mediamarkt.es/es/search.html?query="
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_pagina_mediamarkt = None


def buscar_url_producto(termino_busqueda: str, headless: bool = True) -> str | None:
    """
    Busca un término en mediamarkt.es y devuelve la URL de la ficha
    del primer producto encontrado, o None si no hay resultados.

    IMPORTANTE: usa el navegador compartido (ver navegador_compartido.py)
    en vez de abrir uno propio — Playwright no permite tener dos
    navegadores "sync" abiertos a la vez en el mismo programa.
    """
    global _pagina_mediamarkt

    if _pagina_mediamarkt is None:
        try:
            _pagina_mediamarkt = navegador_compartido.nueva_pagina()
        except RuntimeError as error:
            print(f"  [Aviso interno] {error}")
            return None

    url_busqueda = BASE_SEARCH_URL + termino_busqueda.replace(" ", "+")

    try:
        _pagina_mediamarkt.goto(url_busqueda, timeout=35000)
        # Las URLs de ficha de producto siguen siempre el patrón
        # /es/product/..., así que buscamos directamente un enlace
        # con esa forma en vez de depender de una clase CSS
        # concreta (más resistente a cambios de diseño).
        _pagina_mediamarkt.wait_for_selector("a[href*='/es/product/']", timeout=15000)
    except Exception:
        return None

    enlace = _pagina_mediamarkt.query_selector("a[href*='/es/product/']")
    href = enlace.get_attribute("href") if enlace else None

    if href and not href.startswith("http"):
        href = f"https://www.mediamarkt.es{href}"

    return href


def _buscar_oferta_recursivo(nodo):
    """
    Busca un bloque "offers" con precio en CUALQUIER nivel de anidación
    de los datos estructurados (JSON-LD), no solo en la posición más
    superficial.

    Algunas páginas ponen el Product directamente en la raíz (fácil de
    encontrar), pero otras lo envuelven dentro de otro tipo —por
    ejemplo, "BuyAction" con el Product metido dentro de "object"—.
    En vez de intentar adivinar todas las formas posibles de envoltorio,
    recorremos toda la estructura buscando la primera coincidencia.

    Devuelve (precio, titulo) o (None, None) si no se encuentra nada.
    """
    if isinstance(nodo, dict):
        oferta = nodo.get("offers")
        if isinstance(oferta, dict) and "price" in oferta:
            return oferta.get("price"), nodo.get("name")
        if isinstance(oferta, list):
            for una_oferta in oferta:
                if isinstance(una_oferta, dict) and "price" in una_oferta:
                    return una_oferta.get("price"), nodo.get("name")

        for valor in nodo.values():
            precio, titulo = _buscar_oferta_recursivo(valor)
            if precio is not None:
                return precio, titulo

    elif isinstance(nodo, list):
        for elemento in nodo:
            precio, titulo = _buscar_oferta_recursivo(elemento)
            if precio is not None:
                return precio, titulo

    return None, None


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

    # --- Intento 1: datos estructurados JSON-LD ---
    # Es el método más fiable si la web lo incluye, porque no depende
    # de clases CSS que puedan cambiar con el diseño. Buscamos en
    # cualquier nivel de anidación (ver _buscar_oferta_recursivo).
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            datos = json.loads(script.string)
        except (TypeError, ValueError):
            continue

        precio, titulo = _buscar_oferta_recursivo(datos)
        if precio is not None:
            try:
                resultado["precio"] = float(precio)
                resultado["titulo"] = titulo
                resultado["encontrado"] = True
                return resultado
            except (TypeError, ValueError):
                pass

    # --- Intento 2 (respaldo): buscar un patrón de precio en el texto ---
    # Solo se usa si no había datos estructurados. Menos fiable, pero
    # sirve como red de seguridad.
    #
    # MediaMarkt a veces escribe los precios redondos con un guion en
    # vez de ",00" (por ejemplo "1099,– €" en vez de "1099,00 €") — se
    # contempla ese caso además del formato normal con decimales.
    texto = soup.get_text(" ", strip=True)

    coincidencia = re.search(r"(\d{1,4}(?:[.,]\d{3})?)[.,](\d{2})\s*€", texto)
    if coincidencia:
        precio_texto = (coincidencia.group(1) + "," + coincidencia.group(2)).replace(".", "").replace(",", ".")
        try:
            resultado["precio"] = float(precio_texto)
            resultado["encontrado"] = True
        except ValueError:
            pass
    else:
        coincidencia_redonda = re.search(r"(\d{1,4}(?:[.,]\d{3})?),[–-]\s*€", texto)
        if coincidencia_redonda:
            precio_texto = coincidencia_redonda.group(1).replace(".", "").replace(",", "")
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
    """
    Función de conveniencia: hace las dos fases seguidas.

    Devuelve SIEMPRE una URL utilizable, aunque no se consiga el precio:
      - url_producto: la ficha exacta del producto, si se encontró.
      - url_busqueda: el enlace a la búsqueda en MediaMarkt con este
        mismo término, como alternativa para comprobarlo a mano si el
        scraper no consigue el precio automáticamente (por ejemplo, si
        MediaMarkt bloquea la petición automatizada).
    """
    url_busqueda_directa = BASE_SEARCH_URL + termino_busqueda.replace(" ", "+")

    url = buscar_url_producto(termino_busqueda, headless=headless)
    if not url:
        return {
            "encontrado": False,
            "precio": None,
            "titulo": None,
            "url_producto": None,
            "url_busqueda": url_busqueda_directa,
        }

    datos = obtener_precio_producto(url)
    datos["url_producto"] = url
    datos["url_busqueda"] = url_busqueda_directa
    return datos


if __name__ == "__main__":
    navegador_compartido.iniciar()
    try:
        termino = "iphone 15 128gb negro"
        print(f"Buscando: {termino}")
        resultado = buscar_precio_mediamarkt(termino, headless=False)
        print(resultado)
    finally:
        navegador_compartido.cerrar()




