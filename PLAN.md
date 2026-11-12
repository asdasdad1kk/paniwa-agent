# Plan de desarrollo — Harness Studio 2

## Objetivo

Herramienta local y distribuible que prepare contexto e instrucciones de alta señal para usarlos manualmente en cualquier chat de LLM. La persona copia el prompt, revisa la respuesta y decide qué hacer con ella. El harness no se conecta a proveedores, no automatiza el chat y no aplica cambios al proyecto.

## Decisiones de producto (v2)

- **Doble superficie:** interfaz de escritorio con PySide6 + qfluentwidgets y CLI para scripts. El núcleo queda separado en `harnesskit` y solo usa la biblioteca estándar.
- **Compatibilidad:** `harness.py` conserva la API y los tests originales sin cambios de comportamiento.
- **Privacidad por diseño:** sin red, sin telemetría, sin claves. Todo se guarda en el perfil del usuario.
- **Git opcional y de solo lectura:** estado, diff y `git apply --check`. Jamás se ejecuta `git apply` real.
- **Contexto determinista:** mismo proyecto + mismas opciones ⇒ mismo prompt y mismo hash.
- **Presupuesto explícito:** se reparte entre diff, mapa y archivos, con truncado cabeza/cola y explicación de lo excluido.
- **Seguridad antes de copiar:** detección y redacción de secretos, avisos de rutas sensibles y revisión humana obligatoria.
- **Idioma:** interfaz y mensajes en español; identificadores y código en inglés.

## Arquitectura

```
harness.py                 compatibilidad con la API original
harnesskit/
  models.py                dataclasses compartidas
  config.py                configuración persistente y recientes
  ignore.py                matcher compacto de .gitignore
  scanner.py               escaneo de archivos y metadatos
  gitutils.py              Git de solo lectura
  secrets.py               detección/redacción de secretos
  symbols.py               mapa de símbolos, imports y relacionados
  tokens.py                estimación, truncado y formato
  promptlib.py             12 tareas y 4 formatos
  contextpack.py           empaquetado por presupuesto
  engine.py                orquestación y cachés
  response.py              parsing de respuestas y parches seguros
  history.py               sesiones JSON locales
  scaffolds.py             9 plantillas locales
  clipboard.py             portapapeles multiplataforma
  cli.py                   CLI y flujo interactivo
  ui/                      FluentWindow, páginas, widgets y tema
tests/test_core.py         suite del núcleo (55 pruebas)
test_harness.py            8 pruebas de compatibilidad
```

## Estado v2 — completado

### Núcleo

- [x] Escaneo con `.gitignore` jerárquico, patrones extra, binarios, tamaño máximo y límite de archivos.
- [x] Estado/diff de Git sin escritura, con detección de repositorio y subcarpetas.
- [x] Estimación de tokens conservadora, incluido texto CJK, y truncado cabeza/cola.
- [x] Empaquetado determinista por tiers: cambios → seleccionados → relacionados.
- [x] Mapa de repositorio por AST para Python y regex para otros lenguajes.
- [x] Descubrimiento de imports locales en Python y JavaScript/TypeScript (1–2 niveles).
- [x] Detección y redacción de claves privadas, tokens cloud, JWT, Bearer, URLs con credenciales y asignaciones sensibles.
- [x] 12 tareas y 4 formatos de prompt, con hash estable.
- [x] Parsing de respuestas: bloques con ruta, diffs unificados, fragmentos y diffs sin fences.
- [x] Construcción de parches para archivos nuevos y existentes; rechazo de rutas absolutas, `..` y fuera del proyecto.
- [x] Verificación con `git apply --check`, sin aplicar.
- [x] Historial local con deduplicación, poda y exportación.
- [x] 9 plantillas locales con ZIP opcional y sin sobrescritura.
- [x] Configuración persistente con coerción, límites y proyectos recientes.

### CLI

- [x] `scan`, `prompt`, `git`, `parse`, `check`, `scaffold`, `history`, `gui` e interactivo.
- [x] Salida de diagnóstico por stderr y prompt por stdout para poder pipear.
- [x] `--copy`, `--out`, `--save`, `--print/--no-print` y opciones de contexto.

### Interfaz

- [x] `FluentWindow` con navegación lateral y seis páginas: Espacio de trabajo, Compositor, Respuesta, Plantillas, Historial y Ajustes.
- [x] Árbol de archivos con checkboxes, filtros, estados Git, selección por carpeta y menú contextual.
- [x] Vista previa con resaltado de sintaxis y números de línea.
- [x] Compositor con generación en segundo plano, debounce, medidor de tokens, advertencias y árbol de contexto incluido/excluido.
- [x] Prompt editable, copiar, guardar, enviar al historial y ventana ampliada.
- [x] Revisor de respuestas con segmentos Bloque/Parche, copia, guardado y verificación.
- [x] Historial con estadísticas, búsqueda, detalle, reutilización y exportación.
- [x] Ajustes de tema, acento, tipografía, generación, escaneo, editor y datos locales.
- [x] Paleta alineada con el tema resuelto para que los widgets Qt nativos no queden oscuros sobre una UI clara.

### Pruebas y documentación

- [x] 55 pruebas del núcleo + 8 de compatibilidad, todas pasando.
- [x] `README.md` reescrito para v2.
- [x] Verificación de sintaxis con `compileall`.
- [x] Revisión visual de las seis páginas en tema claro y oscuro, con capturas automatizadas.

## Siguientes pasos

- [ ] Probar el flujo completo con un repositorio real de la empresa y ajustar ergonomía.
- [ ] Validar cada plantilla ejecutando sus propios comandos de verificación.
- [ ] Añadir descubrimiento de imports para Go, Rust y Java/Kotlin.
- [ ] Medir la estimación con tokenizadores reales y calibrar el margen de seguridad.
- [ ] Empaquetar la GUI como ejecutable de Windows (PyInstaller o similar).
- [ ] Añadir exportación de un informe de sesión (prompt + respuesta + parche verificado).
- [ ] Explorar un modo de revisión lado a lado con el diff del proyecto.

## Criterios de aceptación v2

- La GUI arranca con `python -m harnesskit gui` y permite abrir, escanear, seleccionar y generar un prompt.
- La CLI genera prompts reproducibles y los escribe en stdout; los diagnósticos van a stderr.
- No se realiza ninguna llamada de red ni se aplica ningún cambio automáticamente.
- Los secretos detectados se redactan por defecto y se advierte de las rutas sensibles.
- Los parches se validan con `git apply --check` y nunca se aplican.
- `python -m unittest discover -v` pasa completo.
- `harness.py` mantiene la API original y sus 8 pruebas.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Prompt demasiado grande o poco relevante | Presupuesto explícito, tiers, mapa acotado y lista de excluidos visible. |
| Secretos incluidos accidentalmente | Redacción por defecto, avisos de rutas sensibles y revisión antes de copiar. |
| Respuesta del LLM ambigua o peligrosa | No se aplica nada; el parche se muestra y se valida, y la decisión es humana. |
| Dependencia de Qt para la GUI | Núcleo y CLI sin dependencias; la UI es opcional. |
| Estimación de tokens imprecisa | Margen conservador y truncado determinista con nota visible. |
| Plantillas desactualizadas | Scaffolds mínimos, locales y cubiertos por pruebas. |
