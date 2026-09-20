#!/usr/bin/env python3
"""Build the site using only the publishable recipes and saved weekly menus."""

import html
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import markdown
import yaml
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor


ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "recetas"
WEEKS = ROOT / "semanas"
OUTPUT = ROOT / "docs"
ORDER = ["R13", "R15", "R16", "R17", "R14", "R04", "A04"]


def escape(value):
    return html.escape(str(value), quote=True)


def read_recipe(path):
    source = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", source, re.DOTALL)
    if not match:
        raise ValueError(f"{path.name}: falta la cabecera YAML.")
    data = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not isinstance(data, dict) or not body:
        raise ValueError(f"{path.name}: la ficha está vacía o no es válida.")
    for key in ("id", "titulo", "estado"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{path.name}: falta el campo {key}.")
    ingredients = data.get("ingredientes")
    if not isinstance(ingredients, list) or not ingredients:
        raise ValueError(f"{path.name}: faltan los ingredientes.")
    for ingredient in ingredients:
        if (
            not isinstance(ingredient, dict)
            or not isinstance(ingredient.get("ingrediente"), str)
            or not ingredient["ingrediente"].strip()
            or "cantidad" not in ingredient
        ):
            raise ValueError(f"{path.name}: ingrediente sin nombre o cantidad.")
        if ingredient.get("nota") is not None and not isinstance(ingredient["nota"], str):
            raise ValueError(f"{path.name}: la nota de un ingrediente no es texto.")
    return {"path": path, "data": data, "body": body}


def read_week(path):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
        raise ValueError(f"{path.name}: el nombre debe ser una fecha ISO (AAAA-MM-DD).")
    date.fromisoformat(path.stem)
    source = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", source, re.DOTALL)
    if not match:
        raise ValueError(f"{path.name}: falta la cabecera YAML.")
    data = yaml.safe_load(match.group(1))
    body = match.group(2).strip()
    if not isinstance(data, dict) or not body:
        raise ValueError(f"{path.name}: el menú está vacío o no es válido.")
    for key in ("titulo", "estado"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"{path.name}: falta el campo {key}.")
    for key in ("inicio", "fin"):
        try:
            data[key] = date.fromisoformat(str(data.get(key, "")))
        except ValueError as error:
            raise ValueError(f"{path.name}: {key} debe ser una fecha ISO.") from error
    if data["fin"] < data["inicio"]:
        raise ValueError(f"{path.name}: fin no puede ser anterior a inicio.")
    return {"path": path, "data": data, "body": body}


class RecipeLinks(Treeprocessor):
    def run(self, root):
        for link in root.iter("a"):
            target = urlsplit(link.get("href", ""))
            if target.scheme or target.netloc:
                continue
            if target.path == "../combinaciones/platos_sencillos.md":
                link.tag = "span"
                link.attrib.clear()
                for child in list(link):
                    link.remove(child)
                link.text = "catálogo de combinaciones (próximamente)"
            elif target.path.endswith(".md"):
                name = Path(target.path).name
                prefix = self.md.recipe_prefix
                if target.path not in (prefix + name, "./" + prefix + name) or name not in self.md.recipe_names:
                    raise ValueError(f"Enlace local no publicable: {target.path}")
                link.set("href", urlunsplit(("", "", prefix + Path(name).with_suffix(".html").name,
                                             target.query, target.fragment)))


class RecipeLinksExtension(Extension):
    def __init__(self, recipe_names, recipe_prefix=""):
        self.recipe_names = recipe_names
        self.recipe_prefix = recipe_prefix
        super().__init__()

    def extendMarkdown(self, md):
        md.recipe_names = self.recipe_names
        md.recipe_prefix = self.recipe_prefix
        md.treeprocessors.register(RecipeLinks(md), "recipe_links", 15)


def render_markdown(source, recipe_names, recipe_prefix=""):
    return markdown.markdown(source, extensions=["tables", RecipeLinksExtension(recipe_names, recipe_prefix)])


def page(title, content, detail=False, latest_week=None):
    prefix = "../" if detail else ""
    week_link = ""
    if latest_week:
        week_link = f'<a href="{prefix}semanas/{escape(latest_week["path"].stem)}.html">Esta semana</a>'
    return f'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="El recetario de casa: preparaciones habituales y detalles por completar.">
  <title>{escape(title)} · En casa</title>
  <link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>
  <header class="site-header">
    <div class="container header-inner">
      <a class="brand" href="{prefix}index.html">En casa</a>
      <nav class="site-nav" aria-label="Navegación principal"><a href="{prefix}index.html">Recetas</a>{week_link}</nav>
    </div>
  </header>
  <main class="container{' recipe-page' if detail else ''}">
{content}
  </main>
  <footer class="site-footer container">Las fichas se completan conforme las usamos.</footer>
</body>
</html>
'''


def status(data):
    label = "En curso" if data["estado"] == "pendiente_de_completar" else data["estado"].replace("_", " ").capitalize()
    return f'<span class="status">{escape(label)}</span>'


def quantity(ingredient):
    amount = ingredient.get("cantidad")
    if amount is None:
        return "Al gusto" if "al gusto" in str(ingredient.get("nota", "")).lower() else "Por concretar"
    unit = ingredient.get("unidad") or ""
    if isinstance(amount, (int, float)) and amount > 1:
        unit = {"unidad": "unidades", "cucharada": "cucharadas", "cucharadita": "cucharaditas"}.get(unit, unit)
    return f"{str(amount).replace('.', ',')} {unit}".strip()


def ingredient_notes(ingredient):
    note = ingredient.get("nota") or ""
    weight = ingredient.get("referencia_peso")
    references = {
        "crudo": "Peso en crudo.",
        "cocinado": "Peso cocinado.",
        "escurrido": "Peso escurrido.",
        "no_aplica": "",
        None: "Referencia de peso por concretar.",
    }
    reference = references.get(weight, f"Referencia de peso: {weight}.")
    return " ".join(part for part in (reference, note) if part)


def recipe_page(recipe, recipe_names, latest_week=None):
    data = recipe["data"]
    paragraphs = re.split(r"\n\s*\n", recipe["body"], maxsplit=1)
    intro = render_markdown(paragraphs[0], recipe_names)
    body = render_markdown(paragraphs[1] if len(paragraphs) > 1 else "", recipe_names)
    rows = "\n".join(
        f'<tr><th scope="row">{escape(item["ingrediente"])}</th>'
        f'<td>{escape(quantity(item))}</td><td>{escape(ingredient_notes(item))}</td></tr>'
        for item in data["ingredientes"]
    )
    content = f'''    <a class="breadcrumb" href="../index.html">← Todas las recetas</a>
    <article>
      <header class="recipe-heading">
        <div class="recipe-meta"><span class="recipe-id">{escape(data["id"])}</span>{status(data)}</div>
        <h1>{escape(data["titulo"])}</h1>
        <button class="print-button" type="button" onclick="window.print()">Imprimir receta</button>
      </header>
      <p class="notice">Esta ficha está en curso. Las cantidades de referencia y los detalles pendientes se indican a continuación.</p>
      <div class="recipe-intro">{intro}</div>
      <section class="ingredients" aria-labelledby="ingredientes">
        <h2 id="ingredientes">Ingredientes</h2>
        <div class="table-wrap"><table>
          <thead><tr><th scope="col">Ingrediente</th><th scope="col">Cantidad</th><th scope="col">Notas</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </section>
      <div class="recipe-content">{body}</div>
    </article>'''
    return page(data["titulo"], content, detail=True, latest_week=latest_week)


def week_page(week, recipe_names, latest_week=None):
    data = week["data"]
    body = render_markdown(week["body"], recipe_names, recipe_prefix="../recetas/")
    content = f'''    <a class="breadcrumb" href="../index.html">← Todas las recetas</a>
    <article>
      <header class="recipe-heading">
        <div class="recipe-meta">{status(data)}</div>
        <h1>{escape(data["titulo"])}</h1>
        <p class="week-period">Del {data["inicio"].strftime("%d/%m/%Y")} al {data["fin"].strftime("%d/%m/%Y")}</p>
        <button class="print-button" type="button" onclick="window.print()">Imprimir menú</button>
      </header>
      <div class="recipe-content week-content">{body}</div>
    </article>'''
    return page(data["titulo"], content, detail=True, latest_week=latest_week)


def index_page(recipes, latest_week=None):
    cards = []
    for recipe in recipes:
        data = recipe["data"]
        cards.append(f'''      <a class="recipe-card" href="recetas/{escape(recipe["path"].stem)}.html">
        <div class="card-meta"><span class="recipe-id">{escape(data["id"])}</span>{status(data)}</div>
        <h2>{escape(data["titulo"])}</h2>
        <span class="card-link">Ver receta <span aria-hidden="true">→</span></span>
      </a>''')
    week_banner = ""
    if latest_week:
        week_banner = f'''    <a class="week-banner" href="semanas/{escape(latest_week["path"].stem)}.html">
      <span><span class="eyebrow">Esta semana</span><strong class="week-banner-title">{escape(latest_week["data"]["titulo"])}</strong></span>
      <span aria-hidden="true">→</span>
    </a>'''
    content = f'''    <section class="hero">
      <p class="eyebrow">En casa</p>
      <h1>Nuestro recetario</h1>
      <p class="lead">Las recetas que vamos haciendo nuestras. Ya podemos consultarlas mientras completamos cantidades, tiempos y otros detalles.</p>
    </section>
{week_banner}
    <div class="recipe-grid">
{chr(10).join(cards)}
    </div>'''
    return page("Nuestro recetario", content, latest_week=latest_week)


def main():
    # This explicit, non-recursive input boundary excludes the private project files.
    paths = sorted(RECIPES.glob("*.md"))
    if not paths:
        raise ValueError("No hay fichas en publicable/recetas.")
    if any(path.is_symlink() for path in paths):
        raise ValueError("Las fichas publicables deben ser archivos, no enlaces simbólicos.")
    recipes = [read_recipe(path) for path in paths]
    ids = [recipe["data"]["id"] for recipe in recipes]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay identificadores de receta duplicados.")
    recipes.sort(key=lambda recipe: (ORDER.index(recipe["data"]["id"])
                                    if recipe["data"]["id"] in ORDER else len(ORDER),
                                    recipe["data"]["titulo"]))
    names = {path.name for path in paths}
    week_paths = sorted(WEEKS.glob("*.md"))
    if any(path.is_symlink() for path in week_paths):
        raise ValueError("Los menús publicables deben ser archivos, no enlaces simbólicos.")
    weeks = [read_week(path) for path in week_paths]
    latest_week = weeks[-1] if weeks else None
    # Render and validate all content before writing output.
    pages = {"index.html": index_page(recipes, latest_week)}
    pages.update({f'recetas/{recipe["path"].stem}.html': recipe_page(recipe, names, latest_week) for recipe in recipes})
    pages.update({f'semanas/{week["path"].stem}.html': week_page(week, names, latest_week) for week in weeks})
    style = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    (OUTPUT / "recetas").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "assets").mkdir(parents=True, exist_ok=True)
    if weeks:
        (OUTPUT / "semanas").mkdir(parents=True, exist_ok=True)
    for filename, content in pages.items():
        (OUTPUT / filename).write_text(content, encoding="utf-8")
    (OUTPUT / "assets" / "style.css").write_text(style, encoding="utf-8")
    (OUTPUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Generadas {len(recipes)} recetas y {len(weeks)} semanas en {OUTPUT}")


if __name__ == "__main__":
    main()
