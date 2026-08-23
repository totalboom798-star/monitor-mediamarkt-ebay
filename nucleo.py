"""
Núcleo del sistema.

Por cada tienda activa en la base de datos:
  1. Descarga su catálogo actual de eBay (ebay_client).
  2. Compara con lo que ya conocíamos (tabla 'articulos').
  3. Los artículos que no existían antes se consideran "nuevos":
     se guardan en la base de datos y se avisa por Telegram, incluyendo
     (si se encuentra) el precio del mismo producto en la web oficial
     de MediaMarkt, buscado por título con mediamarkt_scraper.py.
  4. Los artículos que ya existían pero cambiaron de precio se
     actualizan y se guarda el nuevo precio en el histórico.

AVISO sobre la comparación de precios: al no tener el EAN del
artículo (el scraper de tiendas de eBay no lo extrae), la búsqueda en
MediaMarkt se hace por título. Esto puede encontrar ocasionalmente un
producto parecido pero no idéntico (ej. un modelo "Pro" en vez del
estándar) — es una aproximación útil, no una garantía exacta.

Ejecutar con: python nucleo.py
"""

import sqlite3
import time
from datetime import datetime, timezone

import ebay_client
import mediamarkt_scraper
import telegram_bot

DB_PATH = "monitor.db"


def asegurar_columnas_nuevas(conexion):
    """
    Añade columnas nuevas a la tabla 'articulos' si todavía no existen
    (por ejemplo, si la base de datos se creó con una versión anterior
    del esquema). Seguro de ejecutar varias veces.
    """
    cursor = conexion.cursor()
    cursor.execute("PRAGMA table_info(articulos)")
    columnas_existentes = {fila[1] for fila in cursor.fetchall()}

    if "precio_mediamarkt" not in columnas_existentes:
        cursor.execute("ALTER TABLE articulos ADD COLUMN precio_mediamarkt REAL")
        print("Columna 'precio_mediamarkt' añadida a la base de datos.")

    if "mediamarkt_url" not in columnas_existentes:
        cursor.execute("ALTER TABLE articulos ADD COLUMN mediamarkt_url TEXT")
        print("Columna 'mediamarkt_url' añadida a la base de datos.")

    conexion.commit()


def obtener_tiendas_activas(conexion):
    cursor = conexion.cursor()
    cursor.execute("SELECT id, seller_id, nombre_mostrado FROM tiendas WHERE activa = 1")
    return cursor.fetchall()


def procesar_tienda(conexion, tienda_id, seller_id, nombre_mostrado):
    nombre_para_mostrar = nombre_mostrado or seller_id
    print(f"\n--- Procesando tienda: {nombre_para_mostrar} ---")

    cursor = conexion.cursor()
    cursor.execute("SELECT COUNT(*) FROM articulos WHERE tienda_id = ?", (tienda_id,))
    es_primera_carga = cursor.fetchone()[0] == 0

    try:
        articulos_actuales = ebay_client.buscar_articulos_por_tienda(seller_id)
    except Exception as error:
        print(f"  Error al consultar eBay para esta tienda: {error}")
        return

    print(f"  Artículos encontrados en eBay: {len(articulos_actuales)}")
    if es_primera_carga:
        print("  (Primera vez que se ve esta tienda: se guardará sin enviar avisos)")

    nuevos_count = 0
    actualizados_count = 0
    completados_count = 0  # artículos antiguos a los que rellenamos EAN/foto/precio MM
    MAX_COMPLETADOS_POR_TIENDA = 3  # para no disparar el tiempo de proceso de golpe

    for art in articulos_actuales:
        if not art.get("item_id"):
            continue

        cursor.execute(
            "SELECT id, precio, imagen_url, ean FROM articulos WHERE ebay_item_id = ?",
            (art["item_id"],),
        )
        fila_existente = cursor.fetchone()

        if fila_existente is None:
            # --- Artículo NUEVO ---
            cursor.execute(
                """INSERT INTO articulos
                   (ebay_item_id, tienda_id, titulo, precio, moneda, url, imagen_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (art["item_id"], tienda_id, art["titulo"], art["precio"],
                 art.get("moneda", "EUR"), art["url"], art.get("imagen_url")),
            )
            articulo_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO historial_precios (articulo_id, precio) VALUES (?, ?)",
                (articulo_id, art["precio"]),
            )

            # Avisar por Telegram (solo si NO es la primera carga de esta tienda)
            if not es_primera_carga:
                ean, imagen_fiable, precio_oficial, mediamarkt_url = _completar_datos_articulo(art)
                cursor.execute(
                    "UPDATE articulos SET ean = ?, precio_mediamarkt = ?, mediamarkt_url = ?, "
                    "imagen_url = COALESCE(?, imagen_url) WHERE id = ?",
                    (ean, precio_oficial, mediamarkt_url, imagen_fiable, articulo_id),
                )

                try:
                    telegram_bot.enviar_aviso_articulo_nuevo({
                        "titulo": art["titulo"],
                        "precio": art["precio"],
                        "url": art["url"],
                        "tienda_nombre": nombre_para_mostrar,
                        "precio_oficial_mediamarkt": precio_oficial,
                        "precio_oficial_es_aproximado": ean is None,
                        "mediamarkt_url": mediamarkt_url,
                        "imagen_url": imagen_fiable,
                    })
                    cursor.execute(
                        "INSERT INTO notificaciones_enviadas (articulo_id, canal) VALUES (?, 'telegram')",
                        (articulo_id,),
                    )
                    time.sleep(1.2)  # margen de seguridad frente al límite de Telegram
                except Exception as error:
                    print(f"  Aviso: no se pudo enviar la notificación de Telegram: {error}")

            nuevos_count += 1

        else:
            # --- Artículo ya conocido ---
            articulo_id, precio_anterior, imagen_guardada, ean_guardado = fila_existente

            if art["precio"] is not None and art["precio"] != precio_anterior:
                cursor.execute(
                    "UPDATE articulos SET precio = ?, fecha_ultima_actualizacion = ? WHERE id = ?",
                    (art["precio"], datetime.now(timezone.utc).isoformat(), articulo_id),
                )
                cursor.execute(
                    "INSERT INTO historial_precios (articulo_id, precio) VALUES (?, ?)",
                    (articulo_id, art["precio"]),
                )
                actualizados_count += 1

            # "Relleno" progresivo: a los artículos antiguos que se
            # guardaron antes de tener EAN/foto fiable/precio de
            # MediaMarkt, se lo vamos completando poco a poco (solo
            # unos pocos por tienda y ejecución, para no disparar el
            # tiempo de proceso).
            if (not ean_guardado and not es_primera_carga
                    and completados_count < MAX_COMPLETADOS_POR_TIENDA):
                ean, imagen_fiable, precio_oficial, mediamarkt_url = _completar_datos_articulo(art)
                cursor.execute(
                    "UPDATE articulos SET ean = ?, precio_mediamarkt = ?, mediamarkt_url = ?, "
                    "imagen_url = COALESCE(?, imagen_url) WHERE id = ?",
                    (ean, precio_oficial, mediamarkt_url, imagen_fiable, articulo_id),
                )
                completados_count += 1

    conexion.commit()
    print(f"  Nuevos: {nuevos_count} | Precios actualizados: {actualizados_count} | "
          f"Completados (EAN/foto/precio MM antiguos): {completados_count}")


def _completar_datos_articulo(art: dict) -> tuple[str | None, str | None, float | None, str | None]:
    """
    Entra en la ficha del artículo en eBay para sacar el EAN y la foto
    fiable (una sola petición para ambas cosas), y con el EAN (o el
    título si no hay EAN) busca el precio oficial en MediaMarkt.

    Devuelve (ean, imagen_url, precio_oficial, mediamarkt_url). El
    enlace de MediaMarkt SIEMPRE se rellena si es posible (la ficha
    exacta si se encontró, o si no, el enlace a la búsqueda) — así,
    aunque no consigamos el precio automáticamente, queda un enlace
    útil para comprobarlo a mano con un clic.
    """
    ean, imagen_url = None, None
    try:
        detalles = ebay_client.obtener_detalles_articulo(art["item_id"])
        ean = detalles.get("ean")
        imagen_url = detalles.get("imagen_url")
    except Exception as error:
        print(f"  Aviso: no se pudieron obtener los detalles del artículo en eBay: {error}")

    termino_busqueda_mm = ean or art["titulo"]
    precio_oficial = None
    mediamarkt_url = None
    try:
        resultado_mm = mediamarkt_scraper.buscar_precio_mediamarkt(
            termino_busqueda_mm, headless=True
        )
        mediamarkt_url = resultado_mm.get("url_producto") or resultado_mm.get("url_busqueda")
        if resultado_mm.get("encontrado"):
            precio_oficial = resultado_mm.get("precio")
        else:
            print("  Aviso: no se encontró el precio en MediaMarkt "
                  "(puede que no lo tengan, o que la búsqueda automatizada "
                  "haya sido bloqueada). Se deja el enlace de búsqueda como alternativa.")
    except Exception as error:
        print(f"  Aviso: no se pudo consultar MediaMarkt: {error}")
        mediamarkt_url = mediamarkt_scraper.BASE_SEARCH_URL + termino_busqueda_mm.replace(" ", "+")

    return ean, imagen_url, precio_oficial, mediamarkt_url


def main():
    conexion = sqlite3.connect(DB_PATH)
    asegurar_columnas_nuevas(conexion)
    tiendas = obtener_tiendas_activas(conexion)
    print(f"Tiendas activas a procesar: {len(tiendas)}")

    # Un único navegador compartido para toda la ejecución (usado para
    # consultar fichas de artículo de eBay: EAN y foto).
    ebay_client.iniciar_navegador_compartido()
    try:
        for tienda_id, seller_id, nombre_mostrado in tiendas:
            procesar_tienda(conexion, tienda_id, seller_id, nombre_mostrado)
    finally:
        ebay_client.cerrar_navegador_compartido()

    conexion.close()
    print("\nProceso completo.")


if __name__ == "__main__":
    main()


