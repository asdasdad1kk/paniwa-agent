# Harness Studio 2

Ingeniería de contexto **local** para trabajar con cualquier chat de LLM (Copilot Chat, ChatGPT, Claude, Gemini…). El harness prepara un prompt determinista con el contexto exacto de tu repositorio, te deja revisarlo y copiarlo, y después analiza la respuesta para convertirla en un parche que puedes verificar con Git.

- **Sin proveedor de IA integrado.** No hay claves, ni SDKs, ni llamadas de red.
- **Sin automatización del chat.** Tú pegas el prompt y revisas la respuesta.
- **Sin aplicar cambios automáticamente.** El parche solo se genera y se verifica con `git apply --check`; nunca se escribe en el proyecto.
- **Con interfaz de escritorio y CLI.** PySide6 + qfluentwidgets (Fluent Design) y comandos para scripts.

## Qué resuelve

Un chat de LLM solo es útil si recibe el contexto correcto. Elegir archivos a mano es lento, pegar demasiado gasta presupuesto y pegar de menos produce respuestas inventadas. Harness Studio:

1. Escanea el proyecto respetando `.gitignore` y excluyendo dependencias y builds.
2. Selecciona archivos, descubre imports relacionados y añade estado y diff de Git.
3. Reparte un presupuesto de tokens entre diff, mapa de símbolos y archivos, truncando de forma determinista y explicando qué quedó fuera.
4. Detecta y redacta secretos antes de que copies nada.
5. Compone el prompt en Markdown, XML, texto plano o formato compacto.
6. Guarda un historial local de sesiones para reutilizar o exportar.
7. Analiza la respuesta del asistente, extrae bloques y diffs, genera un parche y lo valida.

## Requisitos

- Windows recomendado (también funciona en macOS/Linux con Qt disponible).
- Python 3.10 o posterior (probado con 3.13.1).
- Git opcional: solo se usa para estado, diff y verificación de parches.

El núcleo (`harnesskit` sin `harnesskit.ui`) usa únicamente la biblioteca estándar. La interfaz necesita:

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` instala `PySide6` y `PySide6-Fluent-Widgets`.

## Inicio rápido

### Interfaz gráfica

```powershell
python -m harnesskit gui
python -m harnesskit gui "C:\ruta\a\tu\proyecto"
```

Flujo recomendado:

1. **Espacio de trabajo** — abre una carpeta (o arrástrala). Los archivos con cambios de Git se preseleccionan.
2. Marca el contexto. Usa los filtros *Modificados*, *Seleccionados* y *Código*, o los botones *Cambios*, *Todo* y *Nada*.
3. **Compositor** — elige tarea, escribe la solicitud y ajusta opciones (formato, presupuesto, mapa, diff, imports, numeración, redacción). El prompt se regenera solo.
4. Revisa el prompt y las advertencias. Pulsa **Copiar prompt** y pégalo en tu chat.
5. **Respuesta** — pega la respuesta del asistente. El harness detecta bloques, genera un parche y puede verificarlo con `git apply --check`.
6. **Historial** — reutiliza, exporta o elimina sesiones guardadas en tu perfil.
7. **Plantillas** — crea proyectos iniciales locales (FastAPI, PySide6, React, Express, Angular, Electron…).

Atajos: `Ctrl+O` abrir carpeta, `Ctrl+R` reescanear, `Ctrl+1…5` navegar, `Ctrl+,` ajustes, `Ctrl+Enter` generar el prompt.

### CLI

```powershell
# Escanear y listar archivos con metadatos
python -m harnesskit scan . --limit 40

# Generar un prompt y guardarlo
python -m harnesskit prompt . --task bugfix --changed `
  --request "Corrige el cálculo de reintentos" --out prompt.md

# Incluir patrones concretos y copiar al portapapeles
python -m harnesskit prompt . --task tests --files "src/*.py,tests/*.py" --copy

# Ver estado o diff de Git (solo lectura)
python -m harnesskit git . --diff

# Extraer bloques de una respuesta y generar/validar un parche
python -m harnesskit parse respuesta.md . --patch-out cambios.patch --check

# Validar un parche existente
python -m harnesskit check cambios.patch .

# Plantillas locales
python -m harnesskit scaffold --list
python -m harnesskit scaffold 1 C:\proyectos\mi-api --zip

# Historial local
python -m harnesskit history --limit 20
python -m harnesskit history --export C:\temp\prompts
```

Sin argumentos, `python -m harnesskit` (o `python harness.py`) abre el flujo interactivo de consola. `harness.py` se mantiene como capa de compatibilidad con la API original (`build_prompt`, `scan_files`, `create_project`, `git_output`, `TASKS`, `PROJECT_TEMPLATES`).

## Opciones del prompt

| Opción | Qué hace |
|---|---|
| `--task` | `feature`, `bugfix`, `refactor`, `tests`, `review`, `docs`, `performance`, `security`, `migration`, `explain`, `commit`, `pr` |
| `--format` | `markdown`, `xml`, `plain`, `compact` |
| `--budget` | Tope aproximado de tokens del prompt completo |
| `--repo-map` | Esqueleto de archivos y símbolos, acotado por `--repo-map-tokens` |
| `--diff` / `--diff-only` | Cambios reales de Git; `diff-only` omite el archivo completo si el diff ya lo cubre |
| `--related` / `--related-depth` | Sigue imports locales desde los archivos seleccionados |
| `--line-numbers` | Numera líneas para facilitar referencias `ruta:línea` |
| `--redact` | Sustituye claves y tokens detectados por `«REDACTADO»` |
| `--truncate` | Conserva cabeza y cola de archivos que no caben |

## Privacidad y seguridad

- No hay llamadas de red ni telemetría. El prompt solo sale del equipo cuando **tú** lo pegas.
- La configuración y el historial viven en el perfil del usuario (`%LOCALAPPDATA%` o el directorio de datos de la plataforma). `HARNESS_HOME` permite cambiar esa ubicación.
- El escaneo es de solo lectura. Los únicos archivos que se crean son las plantillas que pidas, los prompts que exportes y las sesiones del historial.
- Los parches se generan en memoria o en un archivo que elijas y solo se validan con `git apply --check`. **Nunca se aplican.**
- La detección de secretos es una red de seguridad heurística, no una garantía. Revisa siempre el prompt antes de copiarlo.

## Pruebas

```powershell
python -m unittest discover -v
```

La suite cubre estimación de tokens, reglas de `.gitignore`, redacción de secretos, escaneo, empaquetado con presupuesto, generación determinista, formatos, parsing de respuestas, construcción segura de parches, historial, configuración, plantillas y símbolos. `test_harness.py` conserva las pruebas de compatibilidad de la API original.

## Estructura

```
harness.py              Capa de compatibilidad con la API original
harnesskit/
  cli.py                Comandos y flujo interactivo
  scanner.py            Escaneo tolerante a .gitignore y binarios
  ignore.py             Matcher de .gitignore sin dependencias
  secrets.py            Detección/redacción de secretos
  symbols.py            Mapa de símbolos e imports relacionados
  tokens.py             Estimación y truncado por presupuesto
  contextpack.py        Reparto determinista del contexto
  promptlib.py          Tareas y formatos de prompt
  engine.py             Orquestación y cachés
  response.py           Parsing de respuestas y parches seguros
  history.py            Sesiones locales en JSON
  scaffolds.py          Plantillas de proyecto
  gitutils.py           Git de solo lectura
  ui/                   Interfaz PySide6 + qfluentwidgets
tests/test_core.py      Suite del núcleo
test_harness.py         Compatibilidad de la API original
```

## Limitaciones conocidas

- La estimación de tokens es aproximada y deliberadamente conservadora; no sustituye al tokenizador exacto de cada modelo.
- El descubrimiento de imports cubre Python y JavaScript/TypeScript; otros lenguajes solo aportan mapa por expresiones regulares.
- La redacción de secretos reduce el riesgo, pero puede producir falsos positivos y falsos negativos.
- El flujo de vuelta sigue siendo manual: revisar la respuesta, generar el parche, validarlo y aplicarlo tú mismo.
