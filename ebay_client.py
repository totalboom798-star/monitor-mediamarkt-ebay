"""
Cliente para obtener el catálogo de una tienda de eBay.

Después de comprobar que tanto la Finding API (retirada en 2025) como
la Browse API (con un filtro de vendedor poco fiable cuando se quiere
listar "todo" sin palabra de búsqueda) no sirven bien para nuestro
caso, la solución más robusta es leer directamente la página pública
de la tienda (https://www.ebay.es/str/<nombre_tienda>), que SÍ viene
con todos los artículos en el HTML inicial (comprobado con una tienda
real) — no hace falta navegador automatizado, con una petición HTTP
normal basta.

Incluye paginación: recorre las páginas de la tienda hasta que no
encuentra más artículos nuevos.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

_sesion = requests.Session()
_sesion.headers.update({})  # se rellena más abajo, tras definir HEADERS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
_sesion.headers.update(HEADERS)
BASE_STORE_URL = "https://www.ebay.es/str/{seller_id}"
MAX_PAGINAS = 20  # límite de seguridad para no quedarnos en un bucle infinito


def _extraer_item_id(href: str) -> str | None:
    """Extrae el ID numérico del artículo a partir de una URL /itm/..."""
    coincidencia = re.search(r"/itm/(\d+)", href)
    return coincidencia.group(1) if coincidencia else None


def _extraer_precio(texto: str) -> float | None:
    """Busca el primer precio con formato '12,34 EUR' en un texto."""
    coincidencia = re.search(r"(\d{1,4}(?:\.\d{3})*,\d{2})\s*EUR", texto)
    if not coincidencia:
        return None
    numero = coincidencia.group(1).replace(".", "").replace(",", ".")
    try:
        return float(numero)
    except ValueError:
        return None


def _articulos_de_una_pagina(seller_id: str, pagina: int) -> list[dict]:
    """Descarga y parsea una única página de la tienda."""
    url = BASE_STORE_URL.format(seller_id=seller_id)
    resp = _sesion.get(url, params={"_pgn": pagina}, timeout=15)

    if not resp.ok:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    enlaces_articulo = soup.find_all("a", href=re.compile(r"/itm/\d+"))

    articulos = {}
    for enlace in enlaces_articulo:
        item_id = _extraer_item_id(enlace["href"])
        if not item_id or item_id in articulos:
            continue

        titulo = enlace.get_text(strip=True)
        if not titulo:
            continue  # algunos <a> solo envuelven la imagen, sin texto

        # El precio suele estar cerca del enlace en el HTML (mismo bloque
        # contenedor). Buscamos en el texto del elemento "padre" cercano.
        contenedor = enlace.find_parent()
        intentos = 0
        texto_contenedor = ""
        while contenedor is not None and intentos < 4:
            texto_contenedor = contenedor.get_text(" ", strip=True)
            if re.search(r"\d,\d{2}\s*EUR", texto_contenedor):
                break
            contenedor = contenedor.find_parent()
            intentos += 1

        precio = _extraer_precio(texto_contenedor)

        articulos[item_id] = {
            "item_id": item_id,
            "titulo": titulo,
            "precio": precio,
            "moneda": "EUR",
            "url": enlace["href"] if enlace["href"].startswith("http")
                   else f"https://www.ebay.es{enlace['href']}",
        }

    return list(articulos.values())


def buscar_articulos_por_tienda(seller_id: str) -> list[dict]:
    """
    Devuelve todos los artículos de una tienda, recorriendo sus páginas
    hasta que una página no aporte artículos nuevos.
    """
    todos = {}

    for pagina in range(1, MAX_PAGINAS + 1):
        if pagina > 1:
            time.sleep(1.5)  # pequeña pausa para no parecer una petición agresiva

        articulos_pagina = _articulos_de_una_pagina(seller_id, pagina)

        nuevos = [a for a in articulos_pagina if a["item_id"] not in todos]
        for art in articulos_pagina:
            todos[art["item_id"]] = art

        if not articulos_pagina or not nuevos:
            break  # ya no hay más páginas con artículos nuevos

    return list(todos.values())


def obtener_ean_de_articulo(item_id: str) -> str | None:
    """
    Entra en la ficha individual de un artículo de eBay y extrae su EAN,
    si está disponible. Es contenido estático (viene en el HTML inicial),
    así que basta con una petición HTTP normal.

    Se usa solo para artículos concretos que nos interesan (los nuevos),
    no para el catálogo completo de una tienda, para no multiplicar
    peticiones innecesariamente.
    """
    url = f"https://www.ebay.es/itm/{item_id}"
    resp = _sesion.get(url, timeout=15)

    if not resp.ok:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    texto = soup.get_text(" ", strip=True)

    # El EAN aparece en la página como "EAN" seguido del número (a veces
    # también etiquetado como "Upc" en la sección de identificadores).
    coincidencia = re.search(r"\bEAN\b\s*([0-9]{8,14})", texto)
    if not coincidencia:
        coincidencia = re.search(r"\bUpc\b\s*([0-9]{8,14})", texto)

    return coincidencia.group(1) if coincidencia else None


if __name__ == "__main__":
    # Prueba manual: ejecuta "python ebay_client.py"
    seller_prueba = "mediamarktbadalona"
    print(f"Buscando artículos de la tienda: {seller_prueba}")
    resultados = buscar_articulos_por_tienda(seller_prueba)
    print(f"Encontrados: {len(resultados)}")
    for art in resultados[:10]:
        print(f"- {art['titulo']} | {art['precio']} {art['moneda']}")

    if resultados:
        primer_item_id = resultados[0]["item_id"]
        print(f"\nProbando a extraer el EAN del artículo {primer_item_id}...")
        ean = obtener_ean_de_articulo(primer_item_id)
        print(f"EAN encontrado: {ean}")

