"""
COGNOS DEIS Chile - Automatizador de descargas (Unificado y Optimizado)
=======================================================================
Descarga automáticamente reportes de "Atenciones de Urgencia" desde http://cognos.deis.cl.
"""

import argparse
import os
import re
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich import print as rprint
from rich.table import Table

# ============================================================================
# CONFIGURACION & CONSTANTES
# ============================================================================

URL_REPORTE = "http://cognos.deis.cl/ibmcognos/cgi-bin/cognos.cgi?b_action=cognosViewer&ui.action=run&ui.object=/content/folder[@name=%27PUB%27]/folder[@name=%27REPORTES%27]/folder[@name=%27Atenciones%20de%20Urgencia%27]/report[@name=%27Atenciones%20Urgencia%20-%20Vista%20por%20semanas%20-%20Servicios%27]&ui.name=Atenciones%20Urgencia%20-%20Vista%20por%20semanas%20-%20Servicios&run.outputFormat=&run.prompt=true"

ANIOS_DISPONIBLES = list(range(2015, 2026))
SERVICIOS_DISPONIBLES = [
    "Aconcagua", "Aisén", "Antofagasta", "Araucanía Norte", "Araucanía Sur", "Arauco", "Arica", "Atacama", "Bíobío",
    "Chiloé", "Concepción", "Coquimbo", "Del Maule", "Del Reloncaví", "Iquique", "Libertador B. O'Higgins",
    "Magallanes", "Metropolitano Central", "Metropolitano Norte", "Metropolitano Occidente", "Metropolitano Oriente",
    "Metropolitano Sur", "Metropolitano Suroriente", "Ñuble", "Osorno", "Talcahuano", "Valdivia",
    "Valparaíso San Antonio", "Viña Del Mar Quillota"
]
TIPOS_ESTABLECIMIENTO = ["Hospital", "SAPU", "SAR", "SUR", "CEAR", "PAME"]

DIR_DESCARGAS = Path("./descargas")
MAX_REINTENTOS = 3
TIMEOUT_REPORTE = 180_000
TIMEOUT_DESCARGA = 120_000
ESPERA_CARGA_PAGINA = 15

console = Console()

# ============================================================================
# LOGGING (Archivo oculto para debug)
# ============================================================================

def setup_logging():
    DIR_DESCARGAS.mkdir(parents=True, exist_ok=True)
    log_file = DIR_DESCARGAS / "log.txt"
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("cognos")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    return logger

# ============================================================================
# UTILIDADES
# ============================================================================

def sanitizar_nombre(nombre: str) -> str:
    nombre = nombre.strip().replace(" ", "_").replace(".", "").replace(",", "")
    nombre = nombre.replace("(", "").replace(")", "").replace("/", "-").replace("\\", "-")
    nombre = re.sub(r'[<>"|?*:]', '', nombre)
    return nombre[:100]

def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")

# ============================================================================
# SCRAPER CORE
# ============================================================================

class CognosScraper:
    def __init__(self, config: dict, logger=None):
        self.config = config
        self.headless = not config.get("visible", False)
        self.log = logger or logging.getLogger("cognos")
        self.playwright = None
        self.browser = None
        self.page = None
        self._select_ids = {}
        self.total_descargados = 0
        self.total_errores = 0
        self.total_saltados = 0

    def iniciar(self):
        self.log.info("[INICIO] Iniciando navegador Chromium...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self.context = self.browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        self.page = self.context.new_page()

    def cerrar(self):
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        self.log.info("[FIN] Navegador cerrado")

    def navegar_al_reporte(self):
        self.log.debug("Navegando a URL del reporte...")
        self.page.goto(URL_REPORTE, wait_until="domcontentloaded", timeout=60_000)
        self.page.wait_for_timeout(ESPERA_CARGA_PAGINA * 1000)

    def descubrir_selectores(self, reintentos: int = 5):
        for _ in range(reintentos):
            selects = self.page.query_selector_all("select")
            self._select_ids = {}
            for sel in selects:
                sel_id = sel.get_attribute("id") or ""
                options = sel.query_selector_all("option")
                if not options: continue
                texts = [o.text_content().strip() for o in options[:5]]
                
                if all(t.isdigit() and 2010 <= int(t) <= 2030 for t in texts if t.isdigit()) and any(t.isdigit() for t in texts):
                    self._select_ids["anio"] = sel_id
                elif any("Semana" in t for t in texts):
                    self._select_ids["semana"] = sel_id
                elif any(t in TIPOS_ESTABLECIMIENTO for t in texts):
                    self._select_ids["tipo_est"] = sel_id
                elif any(t in ("Talcahuano", "Concepción", "Arauco", "Metropolitano Central", "Metropolitano Suroriente", "Osorno", "Arica") for t in texts):
                    self._select_ids["servicio"] = sel_id

            mapped_ids = set(self._select_ids.values())
            for sel in selects:
                sel_id = sel.get_attribute("id") or ""
                if sel_id and sel_id not in mapped_ids:
                    if len(sel.query_selector_all("option")) > 0:
                        self._select_ids["establecimiento"] = sel_id
                        break
            
            if "establecimiento" in self._select_ids and "anio" in self._select_ids:
                return
            self.page.wait_for_timeout(1000)

    def _get_select(self, nombre):
        return self.page.locator(f"#{self._select_ids[nombre]}")

    def aplicar_filtros_base(self, anio: int):
        """Aplica filtros y retorna la lista de establecimientos reales resultantes."""
        self.log.info(f"[CONFIG] Aplicando filtros base para {anio}...")
        self.descubrir_selectores()
        
        # 1. Año
        self._get_select("anio").select_option(label=str(anio))
        self.page.wait_for_timeout(3000)
        self.descubrir_selectores()

        # 2. Semanas
        if self.config.get("semanas") == "TODAS":
            link_id = self._select_ids["semana"].replace("PRMT_SV_", "PRMT_SV_LINK_SELECT_")
            link = self.page.locator(f"#{link_id}")
            if link.count() > 0: link.click()
            else: self._get_select("semana").evaluate("el => { for(let o of el.options) o.selected = true; }")
        else:
            self._get_select("semana").select_option(label=self.config["semanas"])
        
        # 3. Edad (Siempre todas)
        checkboxes = self.page.query_selector_all("input[role='checkbox']") or self.page.query_selector_all("input[type='checkbox']")
        for cb in checkboxes:
            if cb.get_attribute("aria-checked") != "true" and not cb.is_checked():
                cb.click()
                self.page.wait_for_timeout(100)

        # 4. Servicio de Salud
        if self.config["servicio"] != "TODOS":
            sel_serv = self._get_select("servicio")
            # Buscar coincidencia
            val = sel_serv.evaluate(f"""el => {{
                for(let o of el.options) {{
                    if(o.text.toLowerCase().includes('{self.config["servicio"].lower().split()[-1]}')) return o.value;
                }}
                return null;
            }}""")
            if val: sel_serv.select_option(value=val)
        self.page.wait_for_timeout(4000)
        self.descubrir_selectores()

        # 5. Tipo de Establecimiento
        if self.config["tipo_est"] != "TODOS":
            self._get_select("tipo_est").select_option(label=self.config["tipo_est"])
        else:
            link_id = self._select_ids["tipo_est"].replace("PRMT_SV_", "PRMT_SV_LINK_SELECT_")
            link = self.page.locator(f"#{link_id}")
            if link.count() > 0: link.click()
            else: self._get_select("tipo_est").evaluate("el => { for(let o of el.options) o.selected = true; }")
        self.page.wait_for_timeout(4000)
        self.descubrir_selectores()

        # Obtener lista final
        establecimientos = self._get_select("establecimiento").evaluate("""el => {
            return Array.from(el.options).map(o => ({ nombre: o.text.trim(), value: o.value })).filter(o => o.nombre !== '');
        }""")
        return establecimientos

    def descargar_establecimiento(self, anio: int, est: dict, ruta_destino: Path):
        # 1. Seleccionar el hospital directamente (la sesión viene 100% virgen desde ejecutar_scraper)
        self._get_select("establecimiento").select_option(value=est["value"])
        # Pausa vital para que Cognos asimile la nueva seleccion antes de enviar
        self.page.wait_for_timeout(1500)
        
        # 2. Boton "Nueva solicitud"
        boton = self.page.locator("input[value='Nueva solicitud'], button:has-text('Nueva solicitud')")
        link_excel = self.page.locator("a:has-text('Descargar como Excel')")
        
        boton.first.click()

        # 3. Esperar dinámicamente al botón de Excel
        link_excel.wait_for(state="visible", timeout=TIMEOUT_REPORTE)
        self.page.wait_for_timeout(1000)
        
        ruta_destino.parent.mkdir(parents=True, exist_ok=True)
        
        # 4. Capturar descarga de forma robusta en el contexto
        with self.context.expect_event("download", timeout=TIMEOUT_DESCARGA) as download_info:
            link_excel.click()
        download = download_info.value
        download.save_as(str(ruta_destino))
        
        # Cerrar posibles popups residuales
        for p in self.context.pages:
            if p != self.page:
                try: p.close()
                except: pass
        
        if ruta_destino.exists() and ruta_destino.stat().st_size > 0:
            return True
        return False

# ============================================================================
# UI INTERACTIVA (Rich)
# ============================================================================

def mostrar_banner():
    console.print(Panel.fit(
        "[bold cyan]🏥 DEIS COGNOS SCRAPER - CHILE[/bold cyan]\n"
        "[dim]Automatizador de Descarga de Atenciones de Urgencia - Ministerio de Salud[/dim]",
        border_style="cyan"
    ))

def solicitar_servicio():
    console.print("\n[bold yellow]PASO 1: SELECCIÓN DE SERVICIO DE SALUD[/bold yellow]")
    console.print("  [green][0][/green] [bold]TODOS LOS SERVICIOS (Chile Completo)[/bold]")
    for i, serv in enumerate(SERVICIOS_DISPONIBLES, 1):
        console.print(f"  [cyan][{i}][/cyan] {serv}")
            
    while True:
        opc = Prompt.ask("\n➤ Elige número o nombre (ej: 23 o Suroriente)")
        if opc == "0" or opc.lower() in ("todos", "all"): return "TODOS"
        if opc.isdigit() and 1 <= int(opc) <= len(SERVICIOS_DISPONIBLES):
            return SERVICIOS_DISPONIBLES[int(opc) - 1]
        coincidencias = [s for s in SERVICIOS_DISPONIBLES if opc.lower() in s.lower()]
        if len(coincidencias) == 1: return coincidencias[0]
        if not opc.isdigit() and not coincidencias:
            return opc # Si lo escribio perfecto y no esta en la lista, lo aceptamos
        console.print("[red]⚠ Entrada inválida o ambigua.[/red]")

def solicitar_anios():
    console.print("\n[bold yellow]PASO 2: AÑOS ESTADÍSTICOS[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos los años (2015 a 2025)")
    console.print("  [cyan][2][/cyan] Un año específico (ej: 2015)")
    console.print("  [cyan][3][/cyan] Rango de años (ej: 2020-2023)")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2", "3"], default="1")
    
    if opc == "1": return ANIOS_DISPONIBLES
    elif opc == "2":
        while True:
            a = Prompt.ask("➤ Ingresa el año específico (ej: 2024)")
            if a.isdigit() and int(a) in ANIOS_DISPONIBLES:
                return [int(a)]
            console.print("[red]⚠ Año inválido o fuera de rango (2015-2025).[/red]")
    else:
        while True:
            r = Prompt.ask("➤ Ingresa el rango (ej: 2020-2024)")
            if "-" in r:
                partes = r.split("-")
                if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
                    desde, hasta = int(partes[0]), int(partes[1])
                    if desde in ANIOS_DISPONIBLES and hasta in ANIOS_DISPONIBLES and desde <= hasta:
                        return list(range(desde, hasta + 1))
            console.print("[red]⚠ Formato incorrecto o años fuera de rango (ej: 2020-2024).[/red]")

def solicitar_tipo_est():
    console.print("\n[bold yellow]PASO 3: TIPO DE ESTABLECIMIENTO[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos (Hospital, SAPU, SAR, SUR, CEAR, PAME)")
    console.print("  [cyan][2][/cyan] Elegir específico")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2"], default="1")
    if opc == "2":
        for i, t in enumerate(TIPOS_ESTABLECIMIENTO, 1):
            console.print(f"  [cyan][{i}][/cyan] {t}")
        while True:
            idx = Prompt.ask("➤ Número")
            if idx.isdigit() and 1 <= int(idx) <= len(TIPOS_ESTABLECIMIENTO):
                return TIPOS_ESTABLECIMIENTO[int(idx)-1]
            console.print("[red]⚠ Por favor, ingresa un número válido de la lista.[/red]")
    return "TODOS"

def obtener_nombres_establecimientos(config_temp):
    """Obtiene la lista real de nombres usando un scraper headless temporal"""
    logger = setup_logging()
    scraper = CognosScraper(config_temp, logger)
    try:
        scraper.iniciar()
        scraper.navegar_al_reporte()
        return scraper.aplicar_filtros_base(config_temp["anios"][0])
    except Exception as e:
        console.print(f"[red]Error consultando Cognos: {e}[/red]")
        return []
    finally:
        scraper.cerrar()

def solicitar_establecimiento(config_temp):
    console.print("\n[bold yellow]PASO 4: ESTABLECIMIENTOS[/bold yellow]")
    console.print("  [cyan][1][/cyan] Todos los establecimientos (Descarga automática 1 a 1)")
    console.print("  [cyan][2][/cyan] Elegir específico de la lista")
    opc = Prompt.ask("➤ Elige opción", choices=["1", "2"], default="1")
    
    if opc == "2":
        if config_temp["servicio"] != "TODOS":
            with console.status("[bold cyan]⏳ Conectando a Cognos DEIS para obtener los nombres reales...[/bold cyan]", spinner="dots"):
                lista = obtener_nombres_establecimientos(config_temp)
            if lista:
                console.print(f"\n[bold green]Encontrados {len(lista)} recintos:[/bold green]")
                for i, est in enumerate(lista, 1):
                    console.print(f"  [cyan][{i}][/cyan] {est['nombre']}")
                while True:
                    idx = Prompt.ask("➤ Número")
                    if idx.isdigit() and 1 <= int(idx) <= len(lista):
                        return lista[int(idx)-1]
                    console.print("[red]⚠ Por favor, ingresa un número válido de la lista.[/red]")
        else:
            console.print("[yellow]⚠ Si buscas 'Todos los servicios', no se puede listar establecimientos específicos.[/yellow]")
    return "TODOS"

def main_interactivo():
    limpiar_pantalla()
    mostrar_banner()
    
    config = {}
    config["servicio"] = solicitar_servicio()
    config["anios"] = solicitar_anios()
    config["semanas"] = "TODAS"  # Hardcoded segun req para simplificar menu
    config["tipo_est"] = solicitar_tipo_est()
    config["establecimiento"] = solicitar_establecimiento(config)
    
    config["visible"] = False
    
    # Resumen
    est_str = "Todos (Descarga 1 por 1)" if config['establecimiento'] == 'TODOS' else config['establecimiento']['nombre']
    
    tabla = Table(title="📋 RESUMEN DE CONFIGURACIÓN", border_style="green")
    tabla.add_column("Parámetro", style="bold")
    tabla.add_column("Valor", style="cyan")
    tabla.add_row("🏥 Servicio", config['servicio'])
    tabla.add_row("📅 Años", f"{config['anios'][0]} a {config['anios'][-1]}" if len(config['anios'])>1 else str(config['anios'][0]))
    tabla.add_row("📊 Semanas", config['semanas'])
    tabla.add_row("👥 Grupos de edad", "[green]Todos (5 grupos marcados)[/green]")
    tabla.add_row("🏢 Tipo Establecimiento", config['tipo_est'])
    tabla.add_row("📍 Establecimiento", est_str)
    
    console.print()
    console.print(tabla)
    
    if Confirm.ask("\n[bold green]¿Iniciar la descarga?[/bold green]"):
        ejecutar_scraper(config)
    else:
        console.print("[yellow]Operación cancelada.[/yellow]")

# ============================================================================
# EJECUCIÓN
# ============================================================================

def ejecutar_scraper(config):
    logger = setup_logging()
    scraper = CognosScraper(config, logger)
    
    # Usar panel y barras de progreso de rich
    console.print("\n[bold cyan]🚀 INICIANDO AUTOMATIZADOR DE DESCARGAS DEIS...[/bold cyan]")
    
    try:
        with console.status("[bold blue]Inicializando Chromium...[/bold blue]"):
            scraper.iniciar()
        
        for anio in config["anios"]:
            console.print(f"\n[bold magenta]📅 AÑO ESTADÍSTICO: {anio}[/bold magenta]")
            
            with console.status(f"[bold yellow]Configurando filtros base para {anio}...[/bold yellow]"):
                scraper.navegar_al_reporte()
                establecimientos = scraper.aplicar_filtros_base(anio)
                
            if config["establecimiento"] != "TODOS":
                # Filtrar solo el elegido
                establecimientos = [e for e in establecimientos if e["value"] == config["establecimiento"]["value"]]
                
            if not establecimientos:
                console.print(f"[red]⚠ No se encontraron establecimientos para {anio}.[/red]")
                continue
                
            console.print(f"[green]✓ Filtros aplicados. {len(establecimientos)} archivo(s) por descargar.[/green]\n")
            
            # Progress bar para este año
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(complete_style="green", finished_style="blue"),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                
                task_id = progress.add_task(f"Descargando {anio}...", total=len(establecimientos))
                
                is_first_hospital = True
                
                for est in establecimientos:
                    nombre_archivo = f"{anio}_{sanitizar_nombre(est['nombre'])}.xlsx"
                    ruta = DIR_DESCARGAS / str(anio) / nombre_archivo
                    
                    if ruta.exists() and ruta.stat().st_size > 0:
                        scraper.total_saltados += 1
                        progress.console.print(f"[dim]⏭ Saltado (Ya existe): {nombre_archivo}[/dim]")
                        progress.advance(task_id)
                        continue
                        
                    progress.update(task_id, description=f"Descargando: [cyan]{est['nombre']}[/cyan]")
                    
                    # Reintentos
                    exito = False
                    for intento in range(MAX_REINTENTOS):
                        try:
                            # Recarga de seguridad ABSOLUTA (excepto el primer hospital porque ya cargamos la página)
                            if not is_first_hospital:
                                progress.console.print(f"[dim]  ↻ Reiniciando sesión para {est['nombre']}...[/dim]")
                                scraper.navegar_al_reporte()
                                scraper.aplicar_filtros_base(anio)
                                
                            if scraper.descargar_establecimiento(anio, est, ruta):
                                exito = True
                                is_first_hospital = False
                                break
                        except Exception as e:
                            logger.error(f"Intento {intento+1} falló: {e}")
                            if intento < MAX_REINTENTOS - 1:
                                progress.console.print(f"[yellow]⚠ Reintentando {est['nombre']} ({intento+2}/{MAX_REINTENTOS})...[/yellow]")
                            is_first_hospital = False # Obligar recarga total en el reintento

                                
                    if exito:
                        scraper.total_descargados += 1
                        progress.console.print(f"[green]✓ OK: {nombre_archivo}[/green]")
                    else:
                        scraper.total_errores += 1
                        progress.console.print(f"[red]✗ FALLO: {nombre_archivo}[/red]")
                    
                    progress.advance(task_id)
                    time.sleep(1) # Pausa minima para no saturar al servidor

    except KeyboardInterrupt:
        console.print("\n[red]⛔ Proceso cancelado por el usuario.[/red]")
    except Exception as e:
        console.print(f"\n[red]💥 ERROR FATAL: {e}[/red]")
        logger.exception("Error fatal")
    finally:
        scraper.cerrar()
        # Resumen final
        resumen = Panel(
            f"✅ [green]Descargados:[/green] {scraper.total_descargados}\n"
            f"⏭  [yellow]Saltados:[/yellow]    {scraper.total_saltados}\n"
            f"❌ [red]Errores:[/red]       {scraper.total_errores}",
            title="[bold]Resumen de Descargas[/bold]",
            border_style="cyan",
            expand=False
        )
        console.print("\n")
        console.print(resumen)

# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Descarga automatica COGNOS DEIS")
    parser.add_argument("--anio", type=int, help="Descargar solo un anio especifico")
    parser.add_argument("--silencioso", action="store_true", help="No interactivo")
    parser.add_argument("--visible", action="store_true", help="Mostrar navegador")
    args = parser.parse_args()

    if args.silencioso or args.anio:
        # Modo cli automatizado
        config = {
            "servicio": "Metropolitano Suroriente",
            "anios": [args.anio] if args.anio else ANIOS_DISPONIBLES,
            "semanas": "TODAS",
            "tipo_est": "TODOS",
            "establecimiento": "TODOS",
            "visible": args.visible
        }
        ejecutar_scraper(config)
    else:
        # Modo interactivo
        try:
            main_interactivo()
        except KeyboardInterrupt:
            console.print("\n[yellow]Salida solicitada.[/yellow]")

if __name__ == "__main__":
    main()
