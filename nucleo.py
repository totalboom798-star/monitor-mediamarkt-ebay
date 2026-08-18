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

    for art in articulos_actuales:
        if not art.get("item_id"):
            continue

        cursor.execute(
            "SELECT id, precio FROM articulos WHERE ebay_item_id = ?",
            (art["item_id"],),
        )
        fila_existente = cursor.fetchone()

        if fila_existente is None:
            # --- Artículo NUEVO ---
            cursor.execute(
                """INSERT INTO articulos
                   (ebay_item_id, tienda_id, titulo, precio, moneda, url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (art["item_id"], tienda_id, art["titulo"], art["precio"],
                 art.get("moneda", "EUR"), art["url"]),
            )
            articulo_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO historial_precios (articulo_id, precio) VALUES (?, ?)",
                (articulo_id, art["precio"]),
            )

            # Avisar por Telegram (solo si NO es la primera carga de esta tienda)
            if not es_primera_carga:
                # Intentamos sacar el EAN del propio artículo de eBay, para
                # buscar el precio oficial de MediaMarkt de forma fiable.
                # Si no hay EAN, usamos el título como respaldo (aproximado).
                ean = None
                try:
                    ean = ebay_client.obtener_ean_de_articulo(art["item_id"])
                except Exception as error:
                    print(f"  Aviso: no se pudo obtener el EAN: {error}")

                termino_busqueda_mm = ean or art["titulo"]
                precio_oficial = None
                try:
                    resultado_mm = mediamarkt_scraper.buscar_precio_mediamarkt(
                        termino_busqueda_mm, headless=True
                    )
                    if resultado_mm.get("encontrado"):
                        precio_oficial = resultado_mm.get("precio")
                except Exception as error:
                    print(f"  Aviso: no se pudo consultar el precio de MediaMarkt: {error}")

                try:
                    telegram_bot.enviar_aviso_articulo_nuevo({
                        "titulo": art["titulo"],
                        "precio": art["precio"],
                        "url": art["url"],
                        "tienda_nombre": nombre_para_mostrar,
                        "precio_oficial_mediamarkt": precio_oficial,
                        "precio_oficial_es_aproximado": ean is None,
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
            # --- Artículo ya conocido: comprobar si cambió el precio ---
            articulo_id, precio_anterior = fila_existente
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

    conexion.commit()
    print(f"  Nuevos: {nuevos_count} | Precios actualizados: {actualizados_count}")


def main():
    conexion = sqlite3.connect(DB_PATH)
    tiendas = obtener_tiendas_activas(conexion)
    print(f"Tiendas activas a procesar: {len(tiendas)}")

    for tienda_id, seller_id, nombre_mostrado in tiendas:
        procesar_tienda(conexion, tienda_id, seller_id, nombre_mostrado)

    conexion.close()
    print("\nProceso completo.")


if __name__ == "__main__":
    main()

