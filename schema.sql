-- ============================================================
-- Esquema de base de datos: Monitor de tiendas MediaMarkt en eBay
-- Motor: SQLite
-- ============================================================

-- Las 101 tiendas de MediaMarkt en eBay
CREATE TABLE tiendas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT UNIQUE NOT NULL,        -- ej: 'mediamarktbarcelona'
    nombre_mostrado TEXT,                   -- ej: 'MediaMarkt Barcelona'
    activa INTEGER DEFAULT 1,               -- 1 = se vigila, 0 = pausada
    fecha_alta TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Grupos de productos equivalentes (el mismo producto visto en varias tiendas)
CREATE TABLE grupos_equivalentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_producto TEXT,                   -- ej: 'iPhone 15 128GB Azul'
    ean TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cada artículo visto, con su última información conocida
CREATE TABLE articulos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebay_item_id TEXT UNIQUE NOT NULL,      -- ID único del artículo en eBay
    tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
    titulo TEXT NOT NULL,
    precio REAL NOT NULL,
    moneda TEXT DEFAULT 'EUR',
    condicion TEXT,                         -- 'Nuevo', 'Usado', etc.
    url TEXT,
    imagen_url TEXT,
    ean TEXT,                               -- clave para comparar entre tiendas y con la web oficial
    marca TEXT,
    modelo TEXT,
    grupo_id INTEGER REFERENCES grupos_equivalentes(id),
    activo INTEGER DEFAULT 1,               -- 0 si ya no aparece en la tienda
    fecha_visto_primera_vez TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_articulos_tienda ON articulos(tienda_id);
CREATE INDEX idx_articulos_grupo ON articulos(grupo_id);

-- Evolución del precio de un artículo en eBay a lo largo del tiempo
CREATE TABLE historial_precios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL REFERENCES articulos(id),
    precio REAL NOT NULL,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_historial_articulo ON historial_precios(articulo_id);

-- Precio del mismo producto en la web oficial de MediaMarkt
CREATE TABLE precios_mediamarkt_oficial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo_id INTEGER NOT NULL REFERENCES grupos_equivalentes(id),  -- vinculado al producto, no a un listado de eBay concreto
    ean TEXT,
    url_producto_oficial TEXT,
    precio REAL,
    fecha_consulta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    encontrado INTEGER DEFAULT 1            -- 0 si no se localizó el producto en la web oficial
);
CREATE INDEX idx_precio_oficial_grupo ON precios_mediamarkt_oficial(grupo_id);

-- Registro de notificaciones ya enviadas (evita avisar dos veces del mismo artículo)
CREATE TABLE notificaciones_enviadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    articulo_id INTEGER NOT NULL REFERENCES articulos(id),
    canal TEXT NOT NULL,                    -- 'telegram' | 'app'
    fecha_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
