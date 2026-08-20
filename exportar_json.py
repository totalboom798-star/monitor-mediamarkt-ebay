"""
Exporta el contenido de monitor.db a docs/datos.json, para que la app
web (una página estática, sin servidor) pueda leer los datos.

Se ejecuta automáticamente después de nucleo.py en el workflow de
GitHub Actions.

Los "grupos" (mismo producto en varias tiendas) se forman de dos
maneras:
  1. Por EAN (más fiable) — solo disponible para artículos detectados
     como nuevos después de añadir la extracción de EAN.
  2. Por título EXACTO (mismas mayúsculas/minúsculas ignoradas) entre
     tiendas distintas — sirve de red de seguridad para artículos
     antiguos sin EAN guardado, ya que muchas tiendas de MediaMarkt
     publican el mismo artículo con el título idéntico.
Un artículo nunca aparece en dos grupos a la vez: si ya quedó agrupado
por EAN, no se vuelve a agrupar por título.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

DB_PATH = "monitor.db"
SALIDA_PATH = "docs/datos.json"
# Límite de seguridad muy alto: de momento exportamos prácticamente todo
# (para que el buscador de la web encuentre cualquier artículo, no solo
# los más recientes), pero evitamos un crecimiento sin control a muy
# largo plazo.
MAX_ARTICULOS_EXPORTADOS = 20000


def _construir_grupo(clave, criterio, ofertas):
    ofertas_ordenadas = sorted(ofertas, key=lambda o: (o["precio"] is None, o["precio"]))
    return {
        "clave": clave,
        "criterio": criterio,  # "ean" o "titulo"
        "titulo": ofertas_ordenadas[0]["titulo"],
        "imagen_url": next((o["imagen_url"] for o in ofertas_ordenadas if o["imagen_url"]), None),
        "ofertas": [
            {
                "tienda": o["nombre_mostrado"] or o["seller_id"],
                "precio": o["precio"],
                "moneda": o["moneda"],
                "url": o["url"],
            }
            for o in ofertas_ordenadas
        ],
    }


def exportar():
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT t.seller_id, t.nombre_mostrado, COUNT(a.id) AS num_articulos
        FROM tiendas t
        LEFT JOIN articulos a ON a.tienda_id = t.id
        WHERE t.activa = 1
        GROUP BY t.id
        ORDER BY num_articulos DESC
    """)
    tiendas = [dict(fila) for fila in cursor.fetchall()]

    cursor.execute("""
        SELECT a.titulo, a.precio, a.moneda, a.url, a.imagen_url, a.ean,
               a.precio_mediamarkt, a.fecha_visto_primera_vez,
               t.seller_id, t.nombre_mostrado
        FROM articulos a
        JOIN tiendas t ON t.id = a.tienda_id
        ORDER BY a.fecha_visto_primera_vez DESC
        LIMIT ?
    """, (MAX_ARTICULOS_EXPORTADOS,))
    articulos_recientes = [dict(fila) for fila in cursor.fetchall()]

    # --- Todos los artículos activos, para formar los grupos ---
    cursor.execute("""
        SELECT a.ean, a.titulo, a.precio, a.moneda, a.url, a.imagen_url,
               t.seller_id, t.nombre_mostrado
        FROM articulos a
        JOIN tiendas t ON t.id = a.tienda_id
        WHERE a.activo = 1
    """)
    filas = [dict(fila) for fila in cursor.fetchall()]

    grupos = []
    articulos_ya_agrupados = set()  # (seller_id, titulo) ya usados en un grupo por EAN

    # 1) Agrupar por EAN
    por_ean = defaultdict(list)
    for fila in filas:
        if fila["ean"]:
            por_ean[fila["ean"]].append(fila)

    for ean, ofertas in por_ean.items():
        tiendas_distintas = {o["seller_id"] for o in ofertas}
        if len(tiendas_distintas) < 2:
            continue
        grupos.append(_construir_grupo(ean, "ean", ofertas))
        for o in ofertas:
            articulos_ya_agrupados.add((o["seller_id"], o["titulo"].strip().lower()))

    # 2) Agrupar por título exacto (solo lo que no quedó ya agrupado por EAN)
    por_titulo = defaultdict(list)
    for fila in filas:
        clave_titulo = fila["titulo"].strip().lower()
        if (fila["seller_id"], clave_titulo) in articulos_ya_agrupados:
            continue
        por_titulo[clave_titulo].append(fila)

    for titulo_normalizado, ofertas in por_titulo.items():
        tiendas_distintas = {o["seller_id"] for o in ofertas}
        if len(tiendas_distintas) < 2:
            continue
        grupos.append(_construir_grupo(titulo_normalizado, "titulo", ofertas))

    grupos.sort(key=lambda g: len(g["ofertas"]), reverse=True)

    cursor.execute("SELECT COUNT(*) AS total FROM articulos")
    total_articulos = cursor.fetchone()["total"]

    conexion.close()

    datos = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "total_tiendas": len(tiendas),
        "total_articulos": total_articulos,
        "tiendas": tiendas,
        "articulos_recientes": articulos_recientes,
        "grupos": grupos,
    }

    with open(SALIDA_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    print(f"Exportado: {len(tiendas)} tiendas, {len(articulos_recientes)} artículos recientes, "
          f"{len(grupos)} grupos de productos coincidentes -> {SALIDA_PATH}")


if __name__ == "__main__":
    exportar()
