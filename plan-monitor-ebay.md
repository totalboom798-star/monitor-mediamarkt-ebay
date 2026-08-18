# Plan: Monitor de artículos nuevos en tiendas de eBay

## 1. Objetivo

Sistema que vigila una lista de vendedores/tiendas de eBay, detecta artículos nuevos que publican y compara artículos equivalentes entre esas tiendas (precio, condición, envío). El resultado se muestra en una **app web** y se notifica también por un **bot de Telegram**, ambos alimentados por el mismo núcleo.

**Contexto confirmado:**
- Uso estrictamente personal, sin login de usuarios ni multiusuario.
- ~101 tiendas a vigilar: las distintas cuentas de eBay que tiene MediaMarkt (no tienen una única cuenta central).
- Requisito clave: **todo el proyecto debe ser gratuito** (API, hosting, herramientas).

**Viabilidad económica y de cuota:**
- La API de eBay no tiene coste (no hay tarifas de uso).
- El límite estándar es de ~5.000 llamadas/día por aplicación (no por usuario).
- Con 101 tiendas y ~1 llamada por tienda por ronda de comprobación (la Browse API devuelve hasta 200 artículos por página), se gastarían ~101 llamadas por ronda → se podría comprobar todo el listado hasta ~49 veces al día sin agotar la cuota. Sobra margen de sobra para revisar cada 30-60 minutos.
- El hosting gratuito (backend/worker, base de datos, bot) se decidirá en detalle cuando lleguemos a la fase de despliegue, pero se tendrá en cuenta como restricción de diseño desde el principio.

---

## 2. Arquitectura general

```
                    ┌─────────────────────┐
                    │   eBay Browse API    │
                    └──────────┬───────────┘
                               │ (consulta periódica)
                    ┌──────────▼───────────┐
                    │   NÚCLEO / WORKER     │
                    │  - Consulta eBay      │
                    │  - Detecta artículos  │
                    │    nuevos             │
                    │  - Compara artículos  │
                    │    entre tiendas      │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   BASE DE DATOS       │
                    │  (tiendas, artículos, │
                    │   histórico, usuarios)│
                    └──────┬───────────┬────┘
                           │           │
              ┌────────────▼───┐   ┌───▼─────────────┐
              │   APP WEB       │   │   BOT TELEGRAM   │
              │  (panel/lista)  │   │  (avisos push)   │
              └─────────────────┘   └──────────────────┘
```

El **núcleo** es la única pieza que habla con eBay. Todo lo demás (web y bot) lee de la base de datos o recibe eventos del núcleo. Así evitamos duplicar lógica y mantenemos consistencia entre ambas salidas.

---

## 3. Componentes

### 3.1 Núcleo / Worker (el corazón del sistema)
- Tarea programada (cron / scheduler) que se ejecuta cada X minutos/horas.
- Por cada tienda vigilada, llama a la eBay Browse API filtrando por vendedor.
- Compara los IDs de artículos recibidos contra los que ya existían en la base de datos.
- Los artículos nuevos se insertan en la BD y generan un "evento de artículo nuevo".
- Ese evento dispara: (a) guardado para la app web, (b) mensaje al bot de Telegram.
- Módulo aparte de "comparación": agrupa artículos equivalentes entre tiendas (por EAN/UPC si existe, o por similitud de título + marca + modelo) y calcula quién tiene el mejor precio.

### 3.2 Base de datos
Tablas principales:
- `tiendas` (vendedor eBay, nombre, activo/inactivo)
- `articulos` (item_id de eBay, tienda, título, precio, condición, url, imagen, fecha_visto_primera_vez)
- `historial_precios` (articulo_id, precio, fecha) — para ver evolución
- `grupos_equivalentes` (agrupa artículos de distintas tiendas que son "el mismo producto")
- `usuarios` (si la app va a tener login) y sus preferencias de qué tiendas siguen
- `notificaciones_enviadas` (para no avisar dos veces del mismo artículo)

### 3.3 App web
- Panel donde añades/quitas tiendas a vigilar.
- Listado de artículos nuevos, ordenable y filtrable.
- Vista de comparación: mismo producto en varias tiendas, con precios lado a lado.
- Histórico de precios por artículo (gráfico simple).

### 3.4 Bot de Telegram
- Comando para suscribirte a una tienda concreta o a todas.
- Mensaje automático con foto + título + precio + link cuando aparece un artículo nuevo.
- Opcional: comando para preguntar "¿qué hay nuevo hoy en X tienda?".

---

## 4. Integración con eBay: primeros pasos

1. Crear cuenta en **developer.ebay.com** (gratuita).
2. Registrar una aplicación para obtener `App ID / Client ID` y `Client Secret`.
3. Generar un token OAuth de tipo "Client Credentials" (acceso solo lectura a datos públicos, suficiente para este proyecto — no hace falta que el usuario final inicie sesión en eBay).
4. Usar la **Browse API** (`item_summary/search`) filtrando por `seller` para listar artículos de una tienda concreta.
5. Revisar límites de uso (rate limits) de la cuenta gratuita antes de decidir cada cuánto tiempo hacer polling — importante para no agotar la cuota si se vigilan muchas tiendas.

---

## 5. Stack tecnológico propuesto

| Parte | Opción sugerida |
|---|---|
| Núcleo/Worker | Node.js o Python, con tarea programada (cron) |
| Base de datos | PostgreSQL o SQLite (si el volumen es bajo) |
| App web | React (frontend) + API REST propia sobre el núcleo |
| Bot Telegram | Librería oficial de Bot API (node-telegram-bot-api o python-telegram-bot) |
| Hosting | Depende de dónde quieras desplegarlo (a decidir más adelante) |

*(Esto es una propuesta de partida — se puede ajustar cuando lleguemos a esa fase.)*

---

## 6. Fases de desarrollo sugeridas

1. **Fase 0 — Cuenta y acceso**: crear cuenta developer de eBay, obtener credenciales, probar una llamada simple a la Browse API.
2. **Fase 1 — Núcleo mínimo**: worker que consulta una tienda, detecta artículos nuevos y los guarda en BD (sin interfaz aún).
3. **Fase 2 — Bot de Telegram**: conectar el núcleo para que avise por Telegram cuando hay artículo nuevo.
4. **Fase 3 — App web básica**: panel para ver tiendas seguidas y artículos nuevos.
5. **Fase 4 — Comparación entre tiendas**: lógica de agrupar artículos equivalentes y comparar precios.
6. **Fase 5 — Pulido**: histórico de precios, filtros, gestión de tiendas desde la propia app/bot.

---

## 7. Puntos ya decididos
- Uso personal, sin login de usuarios.
- ~101 tiendas a vigilar (cuentas de eBay de MediaMarkt).
- Todo el proyecto debe ser gratuito (API, hosting, herramientas).

## 8. Puntos a decidir más adelante
- Dónde se alojará (hosting) el proyecto — se evaluarán opciones gratuitas cuando lleguemos a la fase de despliegue (Fase 3+).
