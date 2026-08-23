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
    """
    Busca el primer precio con formato '12,34 EUR' en un texto.

    En vez de exigir un patrón concreto de separador de miles (punto,
    espacio especial...), capturamos TODO lo que haya justo antes de
    ",XX EUR" que parezca parte del número (dígitos y separadores), y
    limpiamos después. Esto evita fallos como el que tuvimos antes: al
    exigir un máximo de 3 dígitos al principio del número, un precio
    como "1999,00" (cuatro dígitos SEGUIDOS, sin separador alguno)
    perdía el primer dígito porque no había manera de "encajarlo" en el
    patrón, y se quedaba solo con "999,00".
    """
    coincidencia = re.search(r"([\d.\u00a0\u202f]{1,10},\d{2})\s*EUR", texto)
    if not coincidencia:
        return None
    numero = (
        coincidencia.group(1)
        .replace(".", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(",", ".")
    )
    try:
        return float(numero)
    except ValueError:
        return None


def _extraer_precio_cerca(enlace) -> float | None:
    """
    Busca el precio avanzando nodo a nodo DESDE el enlace del artículo
    hacia adelante (en el orden en que aparece el HTML), en vez de
    "subir" por los contenedores padre. Subir por los padres podía
    acabar leyendo un número de un contenedor demasiado amplio (una
    cuota de financiación, un descuento, el precio de OTRO artículo
    cercano...). Avanzando nodo a nodo nos quedamos con lo que está
    realmente pegado al título de este artículo.
    """
    nodo = enlace
    trozos = []
    for _ in range(10):
        nodo = nodo.find_next(string=True)
        if nodo is None:
            break
        texto = str(nodo).strip()
        if texto:
            trozos.append(texto)
            precio = _extraer_precio(" ".join(trozos))
            if precio is not None:
                return precio
        if len(" ".join(trozos)) > 120:
            break  # ya nos hemos alejado demasiado del enlace original
    return None


def _url_imagen_valida(img) -> str | None:
    """
    Comprueba si una etiqueta <img> apunta a una foto real de producto
    de eBay (dominio i.ebayimg.com), mirando cualquier atributo que
    pueda contener la URL (src, data-src, srcset...) en vez de una
    lista fija — así no depende de adivinar el nombre exacto del
    atributo que usa la carga diferida (lazy loading).
    """
    for atributo, valor in img.attrs.items():
        if not isinstance(valor, str):
            continue
        if atributo == "srcset":
            primer_url = valor.split(",")[0].strip().split(" ")[0]
            if primer_url.startswith("http") and "ebayimg" in primer_url:
                return primer_url
        elif valor.startswith("http") and "ebayimg" in valor:
            return valor
    return None


def _extraer_imagen_cerca(enlace) -> str | None:
    """
    Busca la foto del artículo cerca de su enlace: primero mirando
    HACIA ATRÁS (las miniaturas suelen ir justo antes del título en
    este tipo de listados), y si no, hacia adelante. Se filtra por el
    dominio real de las fotos de eBay (ebayimg.com) para no confundir
    con logos o iconos de la propia página.
    """
    img = enlace.find_previous("img")
    if img is not None:
        url = _url_imagen_valida(img)
        if url:
            return url

    img = enlace.find_next("img")
    if img is not None:
        url = _url_imagen_valida(img)
        if url:
            return url

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

        precio = _extraer_precio_cerca(enlace)

        articulos[item_id] = {
            "item_id": item_id,
            "titulo": titulo,
            "precio": precio,
            "moneda": "EUR",
            # La imagen NO se saca de esta página de listado: probamos
            # a hacerlo "adivinando" cuál estaba cerca del enlace, pero
            # a veces cogía la foto de OTRO artículo distinto (o el
            # logo de la tienda). Una foto equivocada es peor que
            # ninguna, así que la foto se obtiene aparte, de forma
            # fiable, de la ficha individual del propio artículo (ver
            # obtener_detalles_articulo).
            "imagen_url": None,
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


_playwright_instancia = None
_navegador_compartido = None
_pagina_compartida = None


def iniciar_navegador_compartido():
    """
    Abre UN ÚNICO navegador (Playwright) que se reutiliza para todas
    las fichas de artículo que haga falta consultar durante esta
    ejecución, en vez de abrir uno nuevo cada vez — mucho más rápido.

    Llamar una vez al principio del programa (en nucleo.py), y
    cerrar_navegador_compartido() al terminar.
    """
    global _playwright_instancia, _navegador_compartido, _pagina_compartida
    from playwright.sync_api import sync_playwright

    _playwright_instancia = sync_playwright().start()
    _navegador_compartido = _playwright_instancia.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    contexto = _navegador_compartido.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="es-ES",
        viewport={"width": 1280, "height": 800},
        extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
    )
    contexto.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    _pagina_compartida = contexto.new_page()


def cerrar_navegador_compartido():
    """Cierra el navegador compartido. Llamar al terminar el programa."""
    global _playwright_instancia, _navegador_compartido, _pagina_compartida
    if _navegador_compartido:
        _navegador_compartido.close()
    if _playwright_instancia:
        _playwright_instancia.stop()
    _navegador_compartido = None
    _pagina_compartida = None


def obtener_detalles_articulo(item_id: str) -> dict:
    """
    Entra en la ficha individual de un artículo de eBay y extrae:
      - ean: el código EAN/UPC, si está disponible.
      - imagen_url: la foto principal del artículo.

    IMPORTANTE: usa el navegador automatizado compartido (ver
    iniciar_navegador_compartido), NO una petición HTTP normal. Se
    comprobó que eBay devuelve una versión reducida/incompleta de la
    ficha de artículo cuando se pide con una petición HTTP simple
    (aunque las páginas de listado de tienda sí funcionan así) —
    probablemente porque esta página necesita ejecutar JavaScript
    para cargar el contenido completo.
    """
    resultado = {"ean": None, "imagen_url": None}

    if _pagina_compartida is None:
        print("  [Aviso interno] El navegador compartido no está iniciado "
              "(falta llamar a iniciar_navegador_compartido); no se puede "
              "consultar la ficha del artículo.")
        return resultado

    url = f"https://www.ebay.es/itm/{item_id}"
    try:
        _pagina_compartida.goto(url, timeout=25000)
        _pagina_compartida.wait_for_timeout(600)  # pequeño margen para que termine de cargar
        contenido = _pagina_compartida.content()
    except Exception as error:
        print(f"  [Aviso interno] No se pudo cargar la ficha del artículo {item_id} "
              f"con el navegador: {error}")
        return resultado

    if len(contenido) < 50000:
        print(f"  [Aviso interno] La ficha del artículo {item_id} sigue siendo "
              f"pequeña incluso con navegador ({len(contenido)} caracteres).")

    soup = BeautifulSoup(contenido, "html.parser")
    texto = soup.get_text(" ", strip=True)

    coincidencia = re.search(r"\bEAN\b\s*([0-9]{8,14})", texto)
    if not coincidencia:
        coincidencia = re.search(r"\bUpc\b\s*([0-9]{8,14})", texto)
    resultado["ean"] = coincidencia.group(1) if coincidencia else None

    # La foto se busca por orden de fiabilidad:
    #   1. window.heroImg: una variable que eBay incluye con la foto
    #      principal exacta de este artículo.
    #   2. Cualquier URL de foto de eBay (dominio i.ebayimg.com).
    #   3. La etiqueta "og:image", como último recurso (comprobando
    #      que sea del dominio de fotos de eBay).
    coincidencia_hero = re.search(r'heroImg\s*=\s*"(https://i\.ebayimg\.com/[^"]+)"', contenido)
    if coincidencia_hero:
        resultado["imagen_url"] = coincidencia_hero.group(1)
    else:
        coincidencia_img = re.search(r"https://i\.ebayimg\.com/images/g/[^\s\"'<>]+", contenido)
        if coincidencia_img:
            resultado["imagen_url"] = coincidencia_img.group(0)
        else:
            etiqueta_imagen = soup.find("meta", property="og:image")
            contenido_etiqueta = etiqueta_imagen.get("content", "") if etiqueta_imagen else ""
            if contenido_etiqueta.startswith("http") and "ebayimg" in contenido_etiqueta:
                resultado["imagen_url"] = contenido_etiqueta
            else:
                print(f"  [Aviso interno] No se encontró ninguna foto para el artículo {item_id}.")

    return resultado


def obtener_ean_de_articulo(item_id: str) -> str | None:
    """Atajo que solo devuelve el EAN (usa obtener_detalles_articulo)."""
    return obtener_detalles_articulo(item_id)["ean"]


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
        print(f"\nProbando a extraer detalles del artículo {primer_item_id} (con navegador)...")
        iniciar_navegador_compartido()
        try:
            detalles = obtener_detalles_articulo(primer_item_id)
            print(f"Detalles encontrados: {detalles}")
        finally:
            cerrar_navegador_compartido()




