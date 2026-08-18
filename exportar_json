"""
Exporta el contenido de monitor.db a docs/datos.json, para que la app
web (una página estática, sin servidor) pueda leer los datos.

Se ejecuta automáticamente después de nucleo.py en el workflow de
GitHub Actions.
"""

import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "monitor.db"
SALIDA_PATH = "docs/datos.json"
MAX_ARTICULOS_RECIENTES = 200


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
               a.fecha_visto_primera_vez, t.seller_id, t.nombre_mostrado
        FROM articulos a
        JOIN tiendas t ON t.id = a.tienda_id
        ORDER BY a.fecha_visto_primera_vez DESC
        LIMIT ?
    """, (MAX_ARTICULOS_RECIENTES,))
    articulos_recientes = [dict(fila) for fila in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) AS total FROM articulos")
    total_articulos = cursor.fetchone()["total"]

    conexion.close()

    datos = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "total_tiendas": len(tiendas),
        "total_articulos": total_articulos,
        "tiendas": tiendas,
        "articulos_recientes": articulos_recientes,
    }

    with open(SALIDA_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    print(f"Exportado: {len(tiendas)} tiendas, {len(articulos_recientes)} artículos recientes -> {SALIDA_PATH}")


if __name__ == "__main__":
    exportar()
