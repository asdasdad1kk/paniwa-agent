"""Local project scaffolds. Data only: no network, no package installation."""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Scaffold:
    key: str
    name: str
    description: str
    tags: tuple[str, ...]
    files: dict[str, str]
    next_steps: tuple[str, ...] = field(default_factory=tuple)


def _json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


FASTAPI_FILES = {
    "main.py": '''"""Punto de entrada de la API."""

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="Mi API", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
''',
    "app/__init__.py": "",
    "app/api/__init__.py": "",
    "app/api/routes.py": '''"""Rutas de ejemplo con validación de entrada."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/items", tags=["items"])

_ITEMS: dict[int, "Item"] = {}


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: float = Field(ge=0)


class Item(ItemCreate):
    id: int


@router.get("", response_model=list[Item])
def list_items() -> list[Item]:
    return list(_ITEMS.values())


@router.post("", response_model=Item, status_code=201)
def create_item(payload: ItemCreate) -> Item:
    item_id = max(_ITEMS, default=0) + 1
    item = Item(id=item_id, **payload.model_dump())
    _ITEMS[item_id] = item
    return item


@router.get("/{item_id}", response_model=Item)
def get_item(item_id: int) -> Item:
    item = _ITEMS.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    return item
''',
    "tests/test_api.py": '''from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_item() -> None:
    created = client.post("/items", json={"name": "Teclado", "price": 49.9})
    assert created.status_code == 201
    item_id = created.json()["id"]

    fetched = client.get(f"/items/{item_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Teclado"
''',
    "requirements.txt": "fastapi\nuvicorn[standard]\npytest\nhttpx\n",
    "README.md": """# API FastAPI

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Documentación interactiva: <http://127.0.0.1:8000/docs>

```powershell
python -m pytest
```
""",
    ".gitignore": "__pycache__/\n.venv/\n*.py[cod]\n.pytest_cache/\n.env\n",
}

PYSIDE6_FILES = {
    "main.py": '''import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mi proyecto")
        self.resize(900, 600)

        central = QWidget()
        layout = QVBoxLayout(central)
        label = QLabel("Listo para construir")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.setCentralWidget(central)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "requirements.txt": "PySide6\n",
    "README.md": "# Escritorio PySide6\n\n`python -m pip install -r requirements.txt` y `python main.py`.\n",
    ".gitignore": "__pycache__/\n.venv/\n*.py[cod]\n",
}

PYSIDE6_FLUENT_FILES = {
    "main.py": '''import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow, NavigationItemPosition, PrimaryPushButton, setTheme, Theme


class HomePage(PrimaryPushButton):
    pass


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mi proyecto Fluent")
        self.resize(1100, 720)

        self.home = PrimaryPushButton(FIF.HOME, "Inicio", self)
        self.home.setObjectName("home")
        self.settings = PrimaryPushButton(FIF.SETTING, "Ajustes", self)
        self.settings.setObjectName("settings")

        self.addSubInterface(self.home, FIF.HOME, "Inicio")
        self.addSubInterface(
            self.settings, FIF.SETTING, "Ajustes", NavigationItemPosition.BOTTOM
        )
        self.navigationInterface.setExpandWidth(220)


def main() -> int:
    setTheme(Theme.AUTO)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "requirements.txt": "PySide6\nPySide6-Fluent-Widgets\n",
    "README.md": "# Escritorio PySide6 + Fluent\n\n`python -m pip install -r requirements.txt` y `python main.py`.\n",
    ".gitignore": "__pycache__/\n.venv/\n*.py[cod]\n",
}

REACT_FILES = {
    "package.json": _json(
        {
            "name": "mi-proyecto",
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
            "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
            "devDependencies": {"@vitejs/plugin-react": "^4.3.4", "vite": "^5.4.11"},
        }
    ),
    "vite.config.js": '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
''',
    "index.html": '''<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Mi proyecto</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
''',
    "src/main.jsx": '''import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import "./style.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
''',
    "src/App.jsx": '''import { useState } from "react";

export default function App() {
  const [count, setCount] = useState(0);

  return (
    <main>
      <h1>Mi proyecto</h1>
      <p>Punto de partida mínimo y funcional.</p>
      <button type="button" onClick={() => setCount((value) => value + 1)}>
        Contador: {count}
      </button>
    </main>
  );
}
''',
    "src/style.css": '''body {
  margin: 0;
  font-family: system-ui, sans-serif;
  background: #f7f7f8;
  color: #1d1d1f;
}

main {
  max-width: 42rem;
  margin: 4rem auto;
  padding: 0 1.5rem;
}

button {
  border: 0;
  border-radius: 8px;
  padding: 0.6rem 1rem;
  background: #2f6df6;
  color: white;
  cursor: pointer;
}
''',
    "README.md": "# React + Vite\n\n`npm install` y `npm run dev`.\n",
    ".gitignore": "node_modules/\ndist/\n.vite/\n",
}

EXPRESS_FILES = {
    "package.json": _json(
        {
            "name": "mi-api",
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {"start": "node src/index.js", "dev": "node --watch src/index.js"},
            "dependencies": {"express": "^4.21.2"},
        }
    ),
    "src/index.js": '''import express from "express";

import healthRouter from "./routes/health.js";

const app = express();
const port = Number(process.env.PORT ?? 3000);

app.use(express.json());
app.use("/health", healthRouter);

app.use((error, _request, response, _next) => {
  console.error(error);
  response.status(500).json({ error: "Error interno" });
});

app.listen(port, () => {
  console.log(`Servidor escuchando en http://127.0.0.1:${port}`);
});
''',
    "src/routes/health.js": '''import { Router } from "express";

const router = Router();

router.get("/", (_request, response) => {
  response.json({ status: "ok" });
});

export default router;
''',
    "README.md": "# Express\n\n`npm install` y `npm start`.\n",
    ".gitignore": "node_modules/\n.env\n",
}

TS_NODE_FILES = {
    "package.json": _json(
        {
            "name": "mi-paquete",
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {
                "build": "tsc -p tsconfig.json",
                "start": "node dist/index.js",
                "dev": "tsx watch src/index.ts",
                "test": "tsx --test test/*.test.ts",
            },
            "devDependencies": {
                "@types/node": "^22.10.2",
                "tsx": "^4.19.2",
                "typescript": "^5.7.2",
            },
        }
    ),
    "tsconfig.json": _json(
        {
            "compilerOptions": {
                "target": "ES2022",
                "module": "NodeNext",
                "moduleResolution": "NodeNext",
                "strict": True,
                "outDir": "dist",
                "rootDir": ".",
                "declaration": True,
                "sourceMap": True,
            },
            "include": ["src", "test"],
        }
    ),
    "src/greet.ts": '''export function greet(name: string): string {
  const clean = name.trim();
  if (!clean) {
    throw new Error("El nombre no puede estar vacío");
  }
  return `Hola, ${clean}`;
}
''',
    "src/index.ts": '''import { greet } from "./greet.js";

console.log(greet(process.argv[2] ?? "mundo"));
''',
    "test/greet.test.ts": '''import assert from "node:assert/strict";
import { test } from "node:test";

import { greet } from "../src/greet.js";

test("saluda con un nombre limpio", () => {
  assert.equal(greet("  Ada  "), "Hola, Ada");
});

test("rechaza nombres vacíos", () => {
  assert.throws(() => greet("   "), /vacío/);
});
''',
    "README.md": "# TypeScript + Node\n\n`npm install`, `npm run dev`, `npm test`.\n",
    ".gitignore": "node_modules/\ndist/\n",
}

ANGULAR_FILES = {
    "package.json": _json(
        {
            "name": "mi-app",
            "private": True,
            "version": "0.1.0",
            "scripts": {
                "start": "ng serve",
                "build": "ng build",
                "test": "ng test",
            },
            "dependencies": {
                "@angular/common": "^18.2.0",
                "@angular/compiler": "^18.2.0",
                "@angular/core": "^18.2.0",
                "@angular/forms": "^18.2.0",
                "@angular/platform-browser": "^18.2.0",
                "@angular/router": "^18.2.0",
                "rxjs": "^7.8.1",
                "tslib": "^2.8.1",
                "zone.js": "^0.14.10",
            },
            "devDependencies": {
                "@angular-devkit/build-angular": "^18.2.0",
                "@angular/cli": "^18.2.0",
                "@angular/compiler-cli": "^18.2.0",
                "typescript": "~5.5.4",
            },
        }
    ),
    "angular.json": _json(
        {
            "$schema": "./node_modules/@angular/cli/lib/config/schema.json",
            "version": 1,
            "newProjectRoot": "projects",
            "projects": {
                "mi-app": {
                    "projectType": "application",
                    "root": "",
                    "sourceRoot": "src",
                    "prefix": "app",
                    "architect": {
                        "build": {
                            "builder": "@angular-devkit/build-angular:application",
                            "options": {
                                "browser": "src/main.ts",
                                "index": "src/index.html",
                                "tsConfig": "tsconfig.json",
                                "styles": ["src/styles.css"],
                            },
                            "configurations": {
                                "production": {"outputHashing": "all"},
                                "development": {"optimization": False, "sourceMap": True},
                            },
                            "defaultConfiguration": "production",
                        },
                        "serve": {
                            "builder": "@angular-devkit/build-angular:dev-server",
                            "configurations": {
                                "production": {"buildTarget": "mi-app:build:production"},
                                "development": {"buildTarget": "mi-app:build:development"},
                            },
                            "defaultConfiguration": "development",
                        },
                    },
                }
            },
        }
    ),
    "tsconfig.json": _json(
        {
            "compileOnSave": False,
            "compilerOptions": {
                "outDir": "./dist/out-tsc",
                "strict": True,
                "noImplicitOverride": True,
                "noPropertyAccessFromIndexSignature": True,
                "noImplicitReturns": True,
                "noFallthroughCasesInSwitch": True,
                "skipLibCheck": True,
                "esModuleInterop": True,
                "sourceMap": True,
                "declaration": False,
                "experimentalDecorators": True,
                "moduleResolution": "bundler",
                "importHelpers": True,
                "target": "ES2022",
                "module": "ES2022",
                "lib": ["ES2022", "dom"],
            },
            "angularCompilerOptions": {
                "enableI18nLegacyMessageIdFormat": False,
                "strictInjectionParameters": True,
                "strictInputAccessModifiers": True,
                "strictTemplates": True,
            },
        }
    ),
    "src/index.html": '''<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <title>Mi app</title>
    <base href="/" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <app-root></app-root>
  </body>
</html>
''',
    "src/main.ts": '''import { bootstrapApplication } from "@angular/platform-browser";

import { AppComponent } from "./app/app.component";

bootstrapApplication(AppComponent).catch((error) => console.error(error));
''',
    "src/app/app.component.ts": '''import { Component } from "@angular/core";

@Component({
  selector: "app-root",
  standalone: true,
  template: `
    <main>
      <h1>Mi app</h1>
      <p>Angular standalone, listo para crecer.</p>
    </main>
  `,
  styles: [
    `
      main {
        max-width: 40rem;
        margin: 4rem auto;
        font-family: system-ui, sans-serif;
      }
    `,
  ],
})
export class AppComponent {}
''',
    "src/styles.css": "body { margin: 0; background: #fafafa; }\n",
    "README.md": "# Angular\n\n`npm install` y `npm start`.\n",
    ".gitignore": "node_modules/\ndist/\n.angular/\n",
}

ELECTRON_FILES = {
    "package.json": _json(
        {
            "name": "mi-app-escritorio",
            "private": True,
            "version": "0.1.0",
            "main": "src/main.js",
            "scripts": {"start": "electron ."},
            "devDependencies": {"electron": "^33.2.1"},
        }
    ),
    "src/main.js": '''const { app, BrowserWindow } = require("electron");
const path = require("node:path");

function createWindow() {
  const window = new BrowserWindow({
    width: 1080,
    height: 720,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  window.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
''',
    "src/preload.js": '''const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("appInfo", {
  version: process.versions.electron,
  platform: process.platform,
});
''',
    "src/renderer/index.html": '''<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'" />
    <title>Mi app</title>
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <main>
      <h1>Mi app</h1>
      <p>Electron con contexto aislado.</p>
      <p id="info"></p>
    </main>
    <script src="./renderer.js"></script>
  </body>
</html>
''',
    "src/renderer/styles.css": "body { font-family: system-ui, sans-serif; margin: 3rem; }\n",
    "src/renderer/renderer.js": '''document.getElementById("info").textContent =
  `Electron ${window.appInfo.version} · ${window.appInfo.platform}`;
''',
    "README.md": "# Electron\n\n`npm install` y `npm start`.\n",
    ".gitignore": "node_modules/\ndist/\n",
}

PY_CLI_FILES = {
    "pyproject.toml": '''[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "mipaquete"
version = "0.1.0"
description = "CLI de ejemplo"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
mipaquete = "mipaquete.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
''',
    "src/mipaquete/__init__.py": '__version__ = "0.1.0"\n',
    "src/mipaquete/cli.py": '''"""CLI mínima y testeable."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mipaquete")
    parser.add_argument("name", nargs="?", default="mundo")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"Hola, {args.name}")
    return 0
''',
    "src/mipaquete/__main__.py": '''from .cli import main

raise SystemExit(main())
''',
    "tests/test_cli.py": '''from mipaquete.cli import main


def test_main_prints_greeting(capsys) -> None:
    assert main(["Ada"]) == 0
    assert "Hola, Ada" in capsys.readouterr().out
''',
    "README.md": """# Paquete Python

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e .
mipaquete Ada
```
""",
    ".gitignore": "__pycache__/\n.venv/\n*.egg-info/\n.pytest_cache/\ndist/\nbuild/\n",
}

SCAFFOLDS: dict[str, Scaffold] = {
    "1": Scaffold(
        key="1",
        name="FastAPI",
        description="API tipada con router modular, validación Pydantic y tests.",
        tags=("Python", "API", "pytest"),
        files=FASTAPI_FILES,
        next_steps=(
            "python -m venv .venv",
            "python -m pip install -r requirements.txt",
            "python -m uvicorn main:app --reload",
        ),
    ),
    "2": Scaffold(
        key="2",
        name="PySide6",
        description="Ventana de escritorio mínima con PySide6 puro.",
        tags=("Python", "Desktop", "Qt"),
        files=PYSIDE6_FILES,
        next_steps=("python -m pip install -r requirements.txt", "python main.py"),
    ),
    "3": Scaffold(
        key="3",
        name="PySide6 + Fluent",
        description="FluentWindow con navegación lateral y tema automático.",
        tags=("Python", "Desktop", "Fluent"),
        files=PYSIDE6_FLUENT_FILES,
        next_steps=("python -m pip install -r requirements.txt", "python main.py"),
    ),
    "4": Scaffold(
        key="4",
        name="React + Vite",
        description="SPA con Vite, componentes funcionales y estilos base.",
        tags=("TypeScript", "Frontend", "Vite"),
        files=REACT_FILES,
        next_steps=("npm install", "npm run dev"),
    ),
    "5": Scaffold(
        key="5",
        name="Express",
        description="API Node ESM con router, JSON y manejo de errores.",
        tags=("JavaScript", "API", "Node"),
        files=EXPRESS_FILES,
        next_steps=("npm install", "npm start"),
    ),
    "6": Scaffold(
        key="6",
        name="TypeScript + Node",
        description="Librería/CLI con tsconfig estricto, tsx y tests nativos.",
        tags=("TypeScript", "Node", "Tests"),
        files=TS_NODE_FILES,
        next_steps=("npm install", "npm test"),
    ),
    "7": Scaffold(
        key="7",
        name="Angular standalone",
        description="Aplicación Angular con componente standalone y build moderno.",
        tags=("TypeScript", "Frontend", "Angular"),
        files=ANGULAR_FILES,
        next_steps=("npm install", "npm start"),
    ),
    "8": Scaffold(
        key="8",
        name="Electron",
        description="App de escritorio con preload aislado y CSP restrictiva.",
        tags=("JavaScript", "Desktop", "Electron"),
        files=ELECTRON_FILES,
        next_steps=("npm install", "npm start"),
    ),
    "9": Scaffold(
        key="9",
        name="Paquete Python",
        description="Paquete instalable con consola, pyproject y pytest.",
        tags=("Python", "CLI", "Packaging"),
        files=PY_CLI_FILES,
        next_steps=("python -m pip install -e .", "mipaquete Ada", "python -m pytest"),
    ),
}

# Backwards-compatible view used by the original harness tests/API.
PROJECT_TEMPLATES = {
    key: {"name": scaffold.name, "files": scaffold.files}
    for key, scaffold in SCAFFOLDS.items()
}


def create_project(template_key: str, destination: Path, make_zip: bool) -> Path | None:
    """Create a new project directory and optionally return the ZIP path."""

    if template_key not in SCAFFOLDS:
        raise ValueError("La plantilla seleccionada no existe.")
    destination = Path(destination).expanduser()
    if not destination.name:
        raise ValueError("Indica una ruta de destino válida.")
    if destination.exists():
        raise FileExistsError(f"La ruta ya existe y no se modificará: {destination}")

    archive_path = destination.parent / f"{destination.name}.zip"
    if make_zip and archive_path.exists():
        raise FileExistsError(f"El ZIP ya existe y no se modificará: {archive_path}")

    scaffold = SCAFFOLDS[template_key]
    destination.mkdir(parents=True)
    try:
        for relative_path, content in scaffold.files.items():
            output_path = destination / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content.encode("utf-8"))
    except OSError:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    if not make_zip:
        return None

    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(destination.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(destination).as_posix())
    except OSError:
        shutil.rmtree(destination, ignore_errors=True)
        archive_path.unlink(missing_ok=True)
        raise
    return archive_path


__all__ = ["PROJECT_TEMPLATES", "SCAFFOLDS", "Scaffold", "create_project"]
