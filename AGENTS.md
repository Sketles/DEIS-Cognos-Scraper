# DEIS Cognos Scraper - Contexto para Agentes IA

## ¿Qué es este proyecto?

Un **web scraper automatizado** que descarga reportes de "Atenciones de Urgencia" desde el sistema **IBM Cognos** del Ministerio de Salud de Chile (DEIS).

- **URL objetivo:** `http://cognos.deis.cl` (sistema público, sin login)
- **Reporte:** "Atenciones Urgencia - Vista por semanas - Servicios"
- **Tecnología del sitio:** IBM Cognos 10 (Java/Dojo toolkit, NO HTML moderno). Los controles de la UI son widgets Java renderizados como `<select>` nativos del DOM.
- **Motor de scraping:** Playwright (Chromium headless)
- **UI del script:** Rich (terminal interactiva con barras de progreso)

## Estructura del proyecto

```
DEIS-Cognos-Scraper/
├── scraper.py          # TODO el código: scraper + UI interactiva + entry point
├── requirements.txt    # playwright>=1.40.0, rich>=13.7.0
├── .gitignore
├── README.md
├── AGENTS.md           # ← Este archivo
└── descargas/          # Carpeta de salida (gitignored)
    ├── log.txt         # Log de debug
    └── por anios/      # Subcarpeta con archivos descargados
        ├── 2015/       # ~29 archivos .xlsx por año
        ├── 2016/
        ├── ...
        └── 2025/
```

## Archivo principal: `scraper.py`

**Todo el proyecto vive en un solo archivo.** Contiene:

### Constantes (líneas 24-45)
- `URL_REPORTE`: URL directa al reporte de Cognos con parámetros
- `ANIOS_DISPONIBLES`: `[2015..2025]`
- `SERVICIOS_DISPONIBLES`: 29 servicios de salud de Chile
- `TIPOS_ESTABLECIMIENTO`: Hospital, SAPU, SAR, SUR, CEAR, PAME
- `DIR_DESCARGAS`: `./descargas`
- Timeouts: `TIMEOUT_REPORTE=180s`, `TIMEOUT_DESCARGA=120s`, `ESPERA_CARGA_PAGINA=15s`

### Clase `CognosScraper` (líneas 81-251)
Métodos clave:
- `iniciar()` → Lanza Chromium headless con Playwright
- `navegar_al_reporte()` → Navega a la URL de Cognos y espera 15s
- `descubrir_selectores()` → Detecta dinámicamente los `<select>` del DOM de Cognos (año, semana, tipo_est, servicio, establecimiento) porque **Cognos genera IDs aleatorios** en cada carga
- `aplicar_filtros_base(anio)` → Selecciona año, semanas (todas), edades (todas), servicio, tipo de establecimiento. Retorna `list[dict]` con `{nombre, value}` de cada establecimiento disponible
- `descargar_establecimiento(anio, est, ruta)` → Selecciona un establecimiento, hace click en "Nueva solicitud", **espera dinámicamente a que el spinner de Cognos desaparezca**, y descarga el Excel

### UI Interactiva Rich (líneas 253-391)
Funciones `solicitar_*()` que muestran un menú paso a paso:
1. Servicio de Salud
2. Años (todos / uno / rango)
3. Tipo de Establecimiento
4. Establecimiento específico o todos

### Ejecución `ejecutar_scraper()` (líneas 396-498)
Loop principal:
- Para cada año → navega al reporte, aplica filtros, obtiene lista de establecimientos
- Para cada establecimiento → **recarga completa de la página entre hospitales** (navegar_al_reporte + aplicar_filtros_base de nuevo)
- Salta archivos que ya existen (idempotente)
- Barra de progreso con Rich
- 3 reintentos por archivo

### Entry Point `main()` (líneas 504-531)
- Modo CLI: `python scraper.py --anio 2016` (usa servicio hardcodeado "Metropolitano Suroriente")
- Modo interactivo: `python scraper.py` (menú Rich paso a paso)

## Cómo funciona Cognos por dentro

> [!IMPORTANT]
> **Esto es CRÍTICO para no romper el scraper.**

### El problema de la espera dinámica
Cognos es un sistema Java antiguo. Cuando seleccionas un establecimiento y haces clic en "Nueva solicitud":
1. Cognos hace un POST a `cognos.cgi`
2. Muestra un spinner (`progress.gif`) mientras el servidor calcula
3. Una vez listo, renderiza la tabla con los datos en el DOM
4. El botón "Descargar como Excel" llama a `window[nameSpace].getRV().runExcel()` que exporta lo que **está actualmente visible en el DOM**

**Si haces clic en "Descargar como Excel" ANTES de que Cognos termine de renderizar**, exportas la tabla vacía o los datos del hospital anterior. Esto fue un bug crítico que se resolvió con espera dinámica al `progress.gif`.

### Los selectores son dinámicos
Cognos genera IDs aleatorios tipo `PRMT_SV_N1234567890` en cada carga de página. Por eso `descubrir_selectores()` detecta cada `<select>` por su contenido (¿tiene años? ¿tiene nombres de servicios? ¿tiene tipos de establecimiento?), no por ID.

### Recarga entre hospitales
El scraper recarga completamente la página entre cada hospital (`navegar_al_reporte()` + `aplicar_filtros_base()`). Esto es **necesario** porque Cognos mantiene estado del lado del servidor (session state) y reutilizar la misma sesión entre hospitales causa corrupción de datos.

## Formato de los Excel descargados

Cada `.xlsx` tiene esta estructura:
- **Filas 0-15**: Headers/metadata (título del reporte, filtros aplicados)
- **Fila 16**: Header de año (ej: `['Total atenciones de urgencia', '2015']`)
- **Fila 17**: Header de semanas (`['Total', '1', '2', ..., '52']`)
- **Filas 18+**: Datos (270 filas de causas médicas × 54 columnas)
  - Columna 0: Nombre de la causa (ej: "IRA Alta (J00-J06)")
  - Columnas 1-53: Valores numéricos por semana estadística

**Un archivo de un solo año:** 276 filas × 54 columnas (1 label + 53 semanas)
**Un archivo de todos los años:** 276 filas × 586 columnas (1 label + ~53 semanas × 11 años)

> [!NOTE]
> Cognos SÍ puede generar un solo Excel con todos los años juntos (586 columnas), pero actualmente el scraper descarga un archivo separado por año.

## Cómo ejecutar

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium

# Modo interactivo (menú Rich)
python scraper.py

# Modo CLI directo
python scraper.py --anio 2020
python scraper.py --anio 2020 --visible  # Ver el navegador

# Archivos se guardan en: descargas/por anios/{año}/{año}_{nombre_establecimiento}.xlsx
```

## Problemas conocidos y lecciones aprendidas

1. **Espera fija = datos corruptos.** Nunca usar `wait_for_timeout(12000)` antes de exportar. Siempre esperar dinámicamente al `progress.gif`.
2. **Reutilizar sesión = datos del hospital anterior.** Siempre recargar la página completa entre hospitales.
3. **Cognos no usa HTML widgets.** Los botones parecen HTML pero son widgets Java/Dojo. El click en "Nueva solicitud" es un `<input type="button">`, no un `<button>`.
4. **El servidor se satura.** Si se hacen muchas descargas seguidas, el tiempo de respuesta de Cognos crece de 5s a 30s+. La espera dinámica maneja esto automáticamente.
5. **Archivos "vacíos" tienen 258 filas × 5 columnas.** Eso es la plantilla por defecto de Cognos cuando no hay datos renderizados aún. Un archivo bueno tiene **270 filas × 54 columnas** (para un solo año).

## Estado actual del proyecto

- ✅ Scraper funcional con espera dinámica
- ✅ UI interactiva Rich con selección de servicio/año/tipo/establecimiento
- ✅ Descargados ~318 archivos (29 establecimientos × 11 años, servicio Metropolitano Suroriente)
- ⏳ Pendiente: opción para descargar todos los años en un solo Excel por hospital (586 columnas)
- ⏳ Pendiente: soporte para otros servicios de salud (actualmente solo probado con "Metropolitano Suroriente")
