"""
Crea la base de datos SQLite a partir de schema.sql y carga dentro las
tiendas de MediaMarkt (desde mediamarkt_seller_ids.txt).

Ejecutar UNA VEZ al principio (o cuando se quiera reiniciar la base de
datos desde cero). Es seguro volver a ejecutarlo: no duplica tiendas
ya existentes.
"""

import sqlite3

DB_PATH = "monitor.db"
SCHEMA_PATH = "schema.sql"
SELLER_IDS_PATH = "mediamarkt_seller_ids.txt"


def crear_base_de_datos():
    conexion = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conexion.executescript(f.read())
    conexion.commit()
    conexion.close()
    print(f"Base de datos creada/verificada en: {DB_PATH}")


def cargar_tiendas():
    with open(SELLER_IDS_PATH, encoding="utf-8") as f:
        seller_ids = [linea.strip() for linea in f if linea.strip()]

    conexion = sqlite3.connect(DB_PATH)
    cursor = conexion.cursor()

    insertadas = 0
    for seller_id in seller_ids:
        cursor.execute(
            "INSERT OR IGNORE INTO tiendas (seller_id) VALUES (?)",
            (seller_id,),
        )
        if cursor.rowcount > 0:
            insertadas += 1

    conexion.commit()
    conexion.close()
    print(f"Tiendas cargadas: {insertadas} nuevas (de {len(seller_ids)} en el archivo)")


if __name__ == "__main__":
    crear_base_de_datos()
    cargar_tiendas()
