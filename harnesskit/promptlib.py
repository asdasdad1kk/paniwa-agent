"""Task presets and prompt composition in several output dialects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import ContextBundle, GenerateOptions
from .tokens import estimate_tokens


@dataclass(frozen=True, slots=True)
class TaskPreset:
    key: str
    label: str
    short: str
    instruction: str
    checklist: tuple[str, ...]
    contract: str


TASKS: tuple[TaskPreset, ...] = (
    TaskPreset(
        key="feature",
        label="Implementar funcionalidad",
        short="Feature nueva, integrada con la arquitectura existente.",
        instruction=(
            "Implementa la funcionalidad descrita. Primero identifica los puntos de extensión "
            "que ya existen y reutilízalos; evita introducir abstracciones nuevas si el código "
            "actual no las necesita."
        ),
        checklist=(
            "¿La solución encaja en la arquitectura y convenciones existentes?",
            "¿Se cubren los caminos de error y los casos límite relevantes?",
            "¿Se añaden o actualizan pruebas proporcionadas al riesgo?",
            "¿Hay cambios colaterales que se puedan eliminar?",
        ),
        contract=(
            "Entrega: (1) plan breve, (2) cambios por archivo con código completo o diff, "
            "(3) pruebas nuevas o actualizadas, (4) comandos exactos de verificación."
        ),
    ),
    TaskPreset(
        key="bugfix",
        label="Corregir un bug",
        short="Causa raíz, corrección mínima y prueba de regresión.",
        instruction=(
            "Investiga la causa raíz antes de proponer el parche. Distingue síntoma, causa y "
            "efecto. Propón la corrección mínima que elimine la causa, no un parche que oculte "
            "el fallo."
        ),
        checklist=(
            "¿Existe una hipótesis de causa raíz comprobable?",
            "¿El cambio mínimo corrige todos los caminos afectados?",
            "¿Hay una prueba de regresión que fallaría sin el parche?",
            "¿Se documenta cualquier comportamiento que cambie a propósito?",
        ),
        contract=(
            "Entrega: (1) causa raíz con evidencia, (2) parche mínimo por archivo, "
            "(3) prueba de regresión, (4) cómo verificar y qué podría romperse."
        ),
    ),
    TaskPreset(
        key="refactor",
        label="Refactorizar",
        short="Cambiar estructura sin cambiar comportamiento observable.",
        instruction=(
            "Refactoriza sin cambiar el comportamiento observable. Define primero qué invariantes "
            "deben mantenerse y divide el trabajo en pasos pequeños y reversibles."
        ),
        checklist=(
            "¿El comportamiento público queda idéntico?",
            "¿Cada paso deja el proyecto compilando y con pruebas verdes?",
            "¿Se evitan renombrados masivos y ruido de formato?",
            "¿Hay pruebas que protegen los invariantes antes de mover código?",
        ),
        contract=(
            "Entrega: (1) invariantes y plan por pasos, (2) diff por archivo, "
            "(3) pruebas que demuestran equivalencia, (4) criterios para revertir."
        ),
    ),
    TaskPreset(
        key="tests",
        label="Diseñar pruebas",
        short="Casos significativos, deterministas y mantenibles.",
        instruction=(
            "Diseña pruebas que detecten fallos reales. Empieza por la tabla de casos: entrada, "
            "condición, resultado esperado y riesgo cubierto. Evita duplicar la implementación en "
            "las aserciones y no abuses de mocks."
        ),
        checklist=(
            "¿Se cubren caminos felices, errores y bordes (vacío, límite, duplicado)?",
            "¿Las pruebas son deterministas y aisladas?",
            "¿Cada mock sustituye una frontera real y no lógica propia?",
            "¿Los nombres describen el comportamiento, no la implementación?",
        ),
        contract=(
            "Entrega: (1) tabla de casos priorizada, (2) código de pruebas completo, "
            "(3) datos/fixtures necesarios, (4) comando para ejecutarlas."
        ),
    ),
    TaskPreset(
        key="review",
        label="Revisar código",
        short="Hallazgos priorizados por severidad con evidencia.",
        instruction=(
            "Revisa el código con foco en bugs, seguridad, concurrencia, rendimiento y contratos "
            "rotos. No propongas reescrituras innecesarias ni discutas estilo salvo que cause un "
            "problema concreto. Si algo es correcto, no lo menciones."
        ),
        checklist=(
            "¿Cada hallazgo indica archivo, línea y escenario de fallo?",
            "¿Está claro el impacto y la probabilidad?",
            "¿La corrección propuesta es proporcionada al riesgo?",
            "¿Se separan defectos de preferencias de estilo?",
        ),
        contract=(
            "Formato por hallazgo: [CRÍTICO|ALTO|MEDIO|BAJO] ruta:línea — problema → impacto → "
            "corrección concreta. Termina con un veredicto y las pruebas que faltan."
        ),
    ),
    TaskPreset(
        key="docs",
        label="Documentar",
        short="Documentación precisa, ejemplos ejecutables y sin inventos.",
        instruction=(
            "Documenta el comportamiento real del código. Cada ejemplo debe poder ejecutarse con "
            "lo que aparece en el contexto; no inventes flags, endpoints ni parámetros."
        ),
        checklist=(
            "¿Está definido el público y qué debe poder hacer al terminar?",
            "¿Los ejemplos usan APIs y rutas que existen en el contexto?",
            "¿Se explican errores, límites y requisitos previos?",
            "¿Se evita repetir información ya obvia en el código?",
        ),
        contract=(
            "Entrega: (1) borrador listo para pegar con encabezados útiles, "
            "(2) ejemplos ejecutables, (3) notas de limitaciones y verificación."
        ),
    ),
    TaskPreset(
        key="performance",
        label="Optimizar rendimiento",
        short="Medir, localizar el cuello de botella y demostrar la mejora.",
        instruction=(
            "No optimices a ciegas. Identifica el cuello de botella con evidencia del contexto, "
            "estima complejidad y propón primero la opción de menor riesgo. Toda mejora debe "
            "poder medirse."
        ),
        checklist=(
            "¿Qué métrica y escenario definen la mejora?",
            "¿Dónde está el coste dominante (CPU, I/O, memoria, red)?",
            "¿La solución cambia el comportamiento o solo el rendimiento?",
            "¿Existe un benchmark reproducible antes/después?",
        ),
        contract=(
            "Entrega: (1) análisis del coste actual, (2) cambio mínimo por archivo, "
            "(3) benchmark o perfil reproducible, (4) riesgos de regresión."
        ),
    ),
    TaskPreset(
        key="security",
        label="Auditar seguridad",
        short="Modelo de amenaza, validación y hallazgos accionables.",
        instruction=(
            "Actúa como revisor de seguridad. Construye un modelo de amenaza mínimo para el "
            "contexto, revisa validación de entrada, autenticación, autorización, secretos, "
            "deserialización, rutas y dependencias. No inventes vulnerabilidades sin una ruta "
            "de explotación plausible."
        ),
        checklist=(
            "¿Quién controla cada entrada y qué privilegios alcanza?",
            "¿Hay secretos, rutas sin validar o confianza implícita?",
            "¿El impacto está descrito como escenario de ataque?",
            "¿La mitigación recomendada es verificable?",
        ),
        contract=(
            "Entrega: (1) modelo de amenaza breve, (2) hallazgos [CRÍTICO|ALTO|MEDIO|BAJO] con "
            "evidencia y escenario, (3) mitigaciones, (4) pruebas de seguridad sugeridas."
        ),
    ),
    TaskPreset(
        key="migration",
        label="Planificar migración",
        short="Cambio incremental, compatible y reversible.",
        instruction=(
            "Diseña una migración incremental. Define compatibilidad hacia atrás, orden de "
            "despliegue, migración de datos y rollback. Prefiere pasos que puedan desplegarse "
            "de forma independiente."
        ),
        checklist=(
            "¿Se puede desplegar sin downtime o con una ventana acotada?",
            "¿Qué pasa con datos y clientes antiguos durante la transición?",
            "¿Cada fase es reversible?",
            "¿Cómo se verifica que la migración terminó bien?",
        ),
        contract=(
            "Entrega: (1) estado actual y objetivo, (2) fases con cambios por archivo, "
            "(3) plan de datos y rollback, (4) criterios de verificación por fase."
        ),
    ),
    TaskPreset(
        key="explain",
        label="Explicar el código",
        short="Mapa mental de arquitectura, flujos y riesgos.",
        instruction=(
            "Explica cómo funciona el código con un modelo mental útil para alguien que va a "
            "modificarlo. Prioriza flujos reales, puntos de entrada y acoplamientos peligrosos "
            "sobre una descripción línea a línea."
        ),
        checklist=(
            "¿Se identifican entrypoints, dependencias y flujo de datos?",
            "¿Se explican las decisiones no obvias y sus consecuencias?",
            "¿Se señalan zonas frágiles o deuda relevante?",
            "¿La explicación permite hacer el siguiente cambio con seguridad?",
        ),
        contract=(
            "Entrega: (1) resumen de una frase, (2) mapa de componentes y flujo, "
            "(3) invariantes y trampas, (4) dónde tocar para un cambio típico."
        ),
    ),
    TaskPreset(
        key="commit",
        label="Mensaje de commit",
        short="Conventional Commits a partir del diff real.",
        instruction=(
            "Genera el mensaje de commit usando únicamente los cambios del diff. El asunto debe "
            "ser imperativo, en minúsculas y de 72 caracteres o menos. El cuerpo explica el porqué "
            "y los efectos, no repite el diff."
        ),
        checklist=(
            "¿El alcance del asunto coincide con el diff?",
            "¿Se indica el tipo correcto (feat, fix, refactor, test, docs, chore)?",
            "¿Se mencionan breaking changes y migraciones?",
            "¿Se evita inventar issues o autores?",
        ),
        contract=(
            "Entrega solo el mensaje listo para pegar: asunto, línea en blanco y cuerpo opcional. "
            "Añade 'BREAKING CHANGE:' si corresponde."
        ),
    ),
    TaskPreset(
        key="pr",
        label="Descripción de PR",
        short="Resumen, cambios, pruebas y riesgos para revisores.",
        instruction=(
            "Redacta la descripción de la pull request a partir del diff y del contexto. El "
            "revisor debe entender qué cambia, por qué y cómo comprobarlo sin leer todo el diff."
        ),
        checklist=(
            "¿El resumen explica el problema y el enfoque?",
            "¿Se listan los cambios por área, no por archivo?",
            "¿Se indican pruebas ejecutadas y las que faltan?",
            "¿Se declaran riesgos, migraciones y rollback?",
        ),
        contract=(
            "Entrega un cuerpo de PR en Markdown con: Resumen, Cambios, Cómo probar, Riesgos, "
            "Notas de revisión. No inventes capturas ni números de issue."
        ),
    ),
)

TASK_BY_KEY = {task.key: task for task in TASKS}
TASK_ORDER = [task.key for task in TASKS]

LEGACY_TASKS = {
    "1": "feature",
    "2": "bugfix",
    "3": "refactor",
    "4": "tests",
    "5": "review",
    "6": "docs",
}

GLOBAL_CONSTRAINTS = (
    "Trabaja solo con el contexto adjunto. No inventes archivos, APIs, dependencias, "
    "comandos ni resultados de ejecución.",
    "Si falta información imprescindible, pide los archivos o datos concretos que necesitas "
    "en lugar de suponer.",
    "Respeta la arquitectura, el estilo y las convenciones existentes. Elimina cambios "
    "colaterales que no aporten a la tarea.",
    "Indica rutas exactas y distingue claramente entre lo verificado y lo supuesto.",
    "Señala riesgos, compatibilidad y pasos de verificación reproducibles.",
    "No repitas el contexto completo en la respuesta; cita solo lo necesario.",
)

FORMAT_LABELS = {
    "markdown": "Markdown",
    "xml": "XML etiquetado",
    "plain": "Texto plano",
    "compact": "Compacto",
}

_FENCE_NAMES = {
    "Python": "python",
    "JavaScript": "javascript",
    "JavaScript (JSX)": "jsx",
    "TypeScript": "typescript",
    "TypeScript (TSX)": "tsx",
    "Vue": "vue",
    "Svelte": "svelte",
    "HTML": "html",
    "CSS": "css",
    "SCSS": "scss",
    "Sass": "sass",
    "Less": "less",
    "JSON": "json",
    "Markdown": "markdown",
    "MDX": "mdx",
    "YAML": "yaml",
    "TOML": "toml",
    "INI": "ini",
    "SQL": "sql",
    "Go": "go",
    "Rust": "rust",
    "Java": "java",
    "Kotlin": "kotlin",
    "Swift": "swift",
    "C": "c",
    "C/C++ header": "cpp",
    "C++": "cpp",
    "C#": "csharp",
    "Ruby": "ruby",
    "PHP": "php",
    "Dart": "dart",
    "Scala": "scala",
    "Elixir": "elixir",
    "Erlang": "erlang",
    "Haskell": "haskell",
    "Lua": "lua",
    "R": "r",
    "Julia": "julia",
    "Perl": "perl",
    "Shell": "bash",
    "PowerShell": "powershell",
    "Batch": "bat",
    "Dockerfile": "dockerfile",
    "Gradle": "groovy",
    "GraphQL": "graphql",
    "Protobuf": "proto",
    "Prisma": "prisma",
    "Terraform": "hcl",
    "HCL": "hcl",
    "XML": "xml",
    "XAML": "xml",
    "Property list": "xml",
    "SVG": "xml",
    "CSV": "csv",
    "Jupyter Notebook": "json",
    "Dotenv": "dotenv",
    "CMake": "cmake",
    "Assembly": "asm",
    "Verilog": "verilog",
    "SystemVerilog": "systemverilog",
    "Solidity": "solidity",
    "Zig": "zig",
    "Nim": "nim",
    "Clojure": "clojure",
    "ClojureScript": "clojure",
    "F#": "fsharp",
    "Git": "gitignore",
    "Docker": "dockerignore",
    "Config": "ini",
    "Properties": "properties",
    "Text": "",
}


def fence_language(language: str) -> str:
    return _FENCE_NAMES.get(language, language.lower().split(" ")[0])


def resolve_task(key: str) -> TaskPreset:
    key = LEGACY_TASKS.get(key, key)
    return TASK_BY_KEY.get(key, TASK_BY_KEY["feature"])


def make_fence(content: str, language: str = "") -> str:
    longest = 0
    run = 0
    for char in content:
        if char == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{content.rstrip()}\n{fence}"


def _markdown(
    task: TaskPreset,
    request: str,
    context: ContextBundle,
    options: GenerateOptions,
) -> str:
    parts: list[str] = [
        "Actúa como ingeniero de software senior. Prioriza corrección, seguridad y cambios "
        "pequeños y verificables.",
        f"## Tarea: {task.label}\n{task.instruction}",
        f"## Solicitud\n{request.strip()}",
        "## Restricciones\n" + "\n".join(f"- {item}" for item in GLOBAL_CONSTRAINTS),
    ]
    if task.checklist:
        parts.append("## Antes de responder, revisa\n" + "\n".join(f"- [ ] {item}" for item in task.checklist))
    if options.custom_instructions.strip():
        parts.append("## Instrucciones adicionales\n" + options.custom_instructions.strip())
    if context.repo_map:
        parts.append("## Mapa del repositorio\n" + make_fence(context.repo_map, "text"))
    if context.git_status:
        parts.append("## Estado de Git\n" + make_fence(context.git_status, "text"))
    if context.git_diff:
        parts.append("## Diff de Git\n" + make_fence(context.git_diff, "diff"))
    if context.files:
        file_blocks = []
        for item in context.files:
            language = fence_language(item.language)
            block = f"### `{item.rel}`"
            if item.note:
                block += f"  \n_{item.note}_"
            block += "\n" + make_fence(item.text, language)
            file_blocks.append(block)
        parts.append("## Archivos de contexto\n" + "\n\n".join(file_blocks))
    elif not (context.repo_map or context.git_diff):
        parts.append(
            "## Archivos de contexto\nNo se adjuntaron archivos. Si la tarea requiere código, "
            "pide exactamente los archivos que necesitas antes de responder."
        )
    if context.redactions == 1:
        parts.append(
            "Nota: se redactó 1 valor potencialmente sensible; no intentes reconstruirlo."
        )
    elif context.redactions:
        parts.append(
            f"Nota: se redactaron {context.redactions} valores potencialmente sensibles; "
            "no intentes reconstruirlos."
        )
    parts.append(f"## Formato de respuesta\n{task.contract}")
    parts.append(
        "Cierra con una lista breve de comprobaciones que debería ejecutar la persona. "
        "No afirmes haber ejecutado nada."
    )
    return "\n\n".join(parts)


def _xml(
    task: TaskPreset,
    request: str,
    context: ContextBundle,
    options: GenerateOptions,
) -> str:
    def cdata(text: str) -> str:
        return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"

    lines: list[str] = [
        "<role>Ingeniero de software senior. Corrección, seguridad y cambios pequeños y verificables.</role>",
        f'<task type="{task.key}" name="{task.label}">',
        cdata(task.instruction),
        "</task>",
        "<request>",
        cdata(request.strip()),
        "</request>",
        "<constraints>",
        "\n".join(f"<rule>{item}</rule>" for item in GLOBAL_CONSTRAINTS),
        "</constraints>",
    ]
    if task.checklist:
        lines.append("<checklist>")
        lines.extend(f"<item>{item}</item>" for item in task.checklist)
        lines.append("</checklist>")
    if options.custom_instructions.strip():
        lines.append("<extra_instructions>")
        lines.append(cdata(options.custom_instructions.strip()))
        lines.append("</extra_instructions>")
    if context.repo_map:
        lines += ["<repository_map>", cdata(context.repo_map), "</repository_map>"]
    if context.git_status:
        lines += ["<git_status>", cdata(context.git_status), "</git_status>"]
    if context.git_diff:
        lines += ['<git_diff format="unified">', cdata(context.git_diff), "</git_diff>"]
    if context.files:
        lines.append("<files>")
        for item in context.files:
            attrs = f'path="{item.rel}" language="{fence_language(item.language) or "text"}"'
            if item.note:
                attrs += f' note="{item.note}"'
            lines += [f"<file {attrs}>", cdata(item.text), "</file>"]
        lines.append("</files>")
    if context.redactions == 1:
        lines.append("<redactions>1 valor sensible redactado</redactions>")
    elif context.redactions:
        lines.append(
            f"<redactions>{context.redactions} valores sensibles redactados</redactions>"
        )
    lines += ["<response_contract>", cdata(task.contract), "</response_contract>"]
    lines.append(
        "<closing>Termina con comprobaciones reproducibles. No afirmes haber ejecutado nada.</closing>"
    )
    return "\n".join(lines)


def _plain(
    task: TaskPreset,
    request: str,
    context: ContextBundle,
    options: GenerateOptions,
) -> str:
    parts = [
        "ROL: Ingeniero de software senior. Prioriza corrección, seguridad y cambios verificables.",
        f"TAREA: {task.label}\n{task.instruction}",
        f"SOLICITUD:\n{request.strip()}",
        "RESTRICCIONES:\n" + "\n".join(f"- {item}" for item in GLOBAL_CONSTRAINTS),
    ]
    if task.checklist:
        parts.append("CHECKLIST:\n" + "\n".join(f"- {item}" for item in task.checklist))
    if options.custom_instructions.strip():
        parts.append("INSTRUCCIONES ADICIONALES:\n" + options.custom_instructions.strip())
    if context.repo_map:
        parts.append("MAPA DEL REPOSITORIO:\n" + context.repo_map)
    if context.git_status:
        parts.append("ESTADO DE GIT:\n" + context.git_status)
    if context.git_diff:
        parts.append("DIFF DE GIT:\n" + context.git_diff)
    for item in context.files:
        parts.append(
            f"ARCHIVO: {item.rel} ({item.language})\n{'-' * 60}\n{item.text.rstrip()}\n{'-' * 60}"
        )
    if context.redactions == 1:
        parts.append("NOTA: 1 valor sensible fue redactado.")
    elif context.redactions:
        parts.append(f"NOTA: {context.redactions} valores sensibles fueron redactados.")
    parts.append(f"FORMATO DE RESPUESTA:\n{task.contract}")
    return "\n\n".join(parts)


def _compact(
    task: TaskPreset,
    request: str,
    context: ContextBundle,
    options: GenerateOptions,
) -> str:
    parts = [
        f"# {task.label}",
        task.instruction,
        f"## Pedido\n{request.strip()}",
        "- No inventes APIs, archivos ni resultados. Pide contexto si falta.",
        "- Cambios mínimos y verificables; señala riesgos y pruebas.",
    ]
    if options.custom_instructions.strip():
        parts.append("## Extra\n" + options.custom_instructions.strip())
    if context.repo_map:
        parts.append("## Mapa\n" + make_fence(context.repo_map, "text"))
    if context.git_status:
        parts.append("## Git\n" + make_fence(context.git_status, "text"))
    if context.git_diff:
        parts.append("## Diff\n" + make_fence(context.git_diff, "diff"))
    for item in context.files:
        parts.append(
            f"## `{item.rel}`\n" + make_fence(item.text, fence_language(item.language))
        )
    if context.redactions == 1:
        parts.append("_(1 secreto redactado)_")
    elif context.redactions:
        parts.append(f"_({context.redactions} secretos redactados)_")
    parts.append(f"## Respuesta\n{task.contract}")
    return "\n\n".join(parts)


def compose_prompt(
    task_key: str,
    request: str,
    context: ContextBundle,
    options: GenerateOptions,
) -> str:
    if not request.strip():
        request = "(La persona no añadió una descripción; infiere la tarea del contexto y confirma supuestos.)"
    task = resolve_task(task_key)
    builders = {
        "markdown": _markdown,
        "xml": _xml,
        "plain": _plain,
        "compact": _compact,
    }
    builder = builders.get(options.format, _markdown)
    return builder(task, request, context, options)


def base_prompt_tokens(task_key: str, request: str, options: GenerateOptions) -> int:
    """Estimate the instruction overhead before packing context."""

    return estimate_tokens(compose_prompt(task_key, request, ContextBundle(), options)) + 120


__all__ = [
    "FORMAT_LABELS",
    "GLOBAL_CONSTRAINTS",
    "LEGACY_TASKS",
    "TASK_BY_KEY",
    "TASK_ORDER",
    "TASKS",
    "TaskPreset",
    "base_prompt_tokens",
    "compose_prompt",
    "fence_language",
    "make_fence",
    "resolve_task",
]
