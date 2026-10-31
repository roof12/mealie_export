#!/usr/bin/env python
import sys
import argparse
import mimetypes
import time
import requests
import json
from jinja2 import Template
from pathlib import Path
from urllib.parse import unquote, urlparse


def slugify(text):
    """Convert text to a slugified version for filenames."""
    if not text:
        return "unnamed-recipe"
    # Lowercase the name, replace all spaces with '-', and replace all underscores with '-'
    slug = text.lower().replace(" ", "-").replace("_", "-")
    return slug if slug else "unnamed-recipe"


def get_api_key_from_file():
    """Read the API key from a file."""
    # Define possible locations for the API key file
    script_dir = Path(__file__).parent
    possible_paths = [
        script_dir / "mealie_api_key.txt"  # Script's directory
    ]

    for path in possible_paths:
        if path.is_file():
            with open(path, "r") as f:
                api_key = f.read().strip()
                if api_key:  # Check if the file contains content
                    return api_key

    # If no valid API key file is found, exit with error message
    print("Error: API key file not found.")
    print("Please create a file containing your API key at one of these locations:")
    for path in possible_paths:
        print(f"  - {path}")
    sys.exit(1)


def fetch_all_recipes(base_url, api_key):
    """Fetch all recipes from the Mealie API, handling pagination."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    page = 1
    all_items = []

    while True:
        params = {
            "page": page,
            "perPage": 50,
            "orderBy": "updatedAt",
            "orderByNullPosition": "last",
            "orderDirection": "desc",
        }

        try:
            response = requests.get(
                f"{base_url}/api/recipes", headers=headers, params=params
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching recipes from API: {e}")
            if e.response is not None:
                print(f"Status code: {e.response.status_code}")
            sys.exit(1)

        items = data.get("items", [])
        all_items.extend(items)
        print(f"  Fetched page {page}: {len(items)} recipes")

        total_pages = data.get("totalPages", data.get("total_pages"))
        if total_pages and page >= total_pages:
            break
        if not items:
            break
        page += 1

    return all_items


def get_recipes(base_url, api_key):
    """Get recipes from the Mealie API."""
    return fetch_all_recipes(base_url, api_key)


def fetch_favorite_recipe_ids(base_url, api_key):
    """Return the IDs of the logged-in user's favorite recipes.

    Favorites are user-specific in Mealie, so they are not part of the recipe
    summary. Older Mealie versions may not expose this endpoint; in that case
    we simply treat every recipe as non-favorite.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.get(
            f"{base_url}/api/users/self/favorites", headers=headers, timeout=30
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Could not fetch favorite recipes (continuing without them): {e}")
        return set()

    # Mealie returns {"ratings": [{"recipeId": ..., "isFavorite": true}, ...]}.
    # Be tolerant of older/newer shapes that return a bare list.
    entries = data.get("ratings", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return set()

    favorite_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not entry.get("isFavorite", entry.get("is_favorite", True)):
            continue
        recipe_id = (
            entry.get("recipeId") or entry.get("recipe_id") or entry.get("id")
        )
        if recipe_id:
            favorite_ids.add(str(recipe_id))

    return favorite_ids


def annotate_favorite_recipes(recipes, favorite_ids):
    """Mark recipe summaries with an isFavorite flag."""
    for recipe in recipes:
        recipe["isFavorite"] = str(recipe.get("id")) in favorite_ids


def get_recipe_details(base_url, api_key, recipe_id):
    """Fetch detailed information for a specific recipe."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.get(f"{base_url}/api/recipes/{recipe_id}", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching details for recipe {recipe_id}: {e}")
        return None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg", ".bmp"}


def sanitize_image_filename(name):
    """Create a filesystem-safe filename stem for a recipe image."""
    sanitized_name = "".join(
        c for c in (name or "") if c.isalnum() or c in (" ", "-", "_")
    ).rstrip()
    return sanitized_name or "unnamed_recipe"


def get_image_extension(url, content_type):
    """Pick an extension from the image URL, falling back to the content type."""
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix

    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed

    return ".webp"


def fetch_images(base_url, api_key, recipes):
    """Download every recipe image locally and point the recipe at that copy."""
    # Determine the parent directory (where the script's parent directory is)
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent

    base = urlparse(base_url)
    auth_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    for recipe in recipes:
        image_value = recipe.get("image")
        if not image_value:
            continue

        parsed = urlparse(image_value)
        if parsed.scheme in ("http", "https") or parsed.netloc:
            image_url = image_value
            if image_url.startswith("//"):
                image_url = f"{base.scheme}:{image_url}"
        elif image_value.startswith("/"):
            # A path relative to the Mealie instance.
            image_url = f"{base_url.rstrip('/')}{image_value}"
        else:
            # Mealie returns an image ID for locally uploaded images.
            recipe_id = recipe.get("id", image_value)
            image_url = (
                f"{base_url.rstrip('/')}/api/media/recipes/{recipe_id}"
                "/images/min-original.webp"
            )

        # Only send the API key to the Mealie instance, never to external image hosts.
        image_parsed = urlparse(image_url)
        headers = {"User-Agent": user_agent}
        if (image_parsed.scheme, image_parsed.netloc) == (base.scheme, base.netloc):
            headers.update(auth_headers)

        response = None
        last_error = None
        for attempt in range(3):
            try:
                response = requests.get(image_url, headers=headers, timeout=60)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < 2:
                    time.sleep(1 + attempt)
        else:
            print(
                f"Error fetching image for recipe '{recipe.get('name', 'Unknown Recipe')}': {last_error}"
            )
            if last_error.response is not None:
                print(f"Status code: {last_error.response.status_code}")
            continue

        filename = parent_dir / (
            sanitize_image_filename(recipe.get("name"))
            + get_image_extension(image_url, response.headers.get("Content-Type"))
        )
        with open(filename, "wb") as f:
            f.write(response.content)

        # Store just the filename. index.html resolves it relative to the parent
        # directory, and recipes/*.html prefix it with "../".
        recipe["image"] = filename.name
        print(f"Downloaded image for recipe '{recipe.get('name', 'Unknown Recipe')}' -> {filename}")


def generate_html_report(recipes, output_file=None):
    """Generate an HTML report using Jinja2 template."""
    # Determine the parent directory (where the script's parent directory is)
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent

    # Set default output file to index.html in parent directory if not provided
    if output_file is None:
        output_file = parent_dir / "index.html"

    # Read the template from an external file
    template_path = script_dir / "templates" / "index.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()

    template = Template(template_str)
    html_content = template.render(recipes=recipes)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"HTML report generated: {output_file}")


def export_data(recipes, export_file):
    """Export recipes data to a JSON file."""
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(recipes, f, indent=2, ensure_ascii=False)
    print(f"Exported data to: {export_file}")


def main():
    parser = argparse.ArgumentParser(description="Export Mealie recipes to HTML")
    parser.add_argument("--url", "-u", required=True, help="Mealie base URL")
    parser.add_argument(
        "--export", "-e", metavar="FILE", help="Path to save exported JSON data"
    )
    args = parser.parse_args()

    api_key = get_api_key_from_file()
    base_url = args.url

    recipes = get_recipes(base_url, api_key)
    print(f"Fetched {len(recipes)} recipes from Mealie API")

    favorite_ids = fetch_favorite_recipe_ids(base_url, api_key)
    annotate_favorite_recipes(recipes, favorite_ids)
    print(f"Found {len(favorite_ids)} favorite recipes")

    # Fetch images for recipes where image field is an ID
    fetch_images(base_url, api_key, recipes)

    # Generate individual recipe detail pages
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent
    recipes_dir = parent_dir / "recipes"
    recipes_dir.mkdir(exist_ok=True)

    recipe_template_path = script_dir / "templates" / "recipe.html"
    with open(recipe_template_path, "r", encoding="utf-8") as f:
        recipe_template_str = f.read()
    recipe_template = Template(recipe_template_str)

    for recipe in recipes:
        recipe_id = recipe.get("id")
        recipe_name = recipe.get("name", "unnamed-recipe")
        if not recipe_id:
            continue

        details = get_recipe_details(base_url, api_key, recipe_id)
        if details:
            details["image"] = recipe.get("image", "")
            details["isFavorite"] = recipe.get("isFavorite", False)
            html_content = recipe_template.render(recipe=details)
            slug = slugify(recipe_name)
            output_file = recipes_dir / f"{slug}.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"Generated detail page for recipe '{recipe_name}' -> {output_file}")

    # Optionally export data to a file
    if args.export:
        export_data(recipes, args.export)

    # Generate HTML report as index.html in parent directory
    generate_html_report(recipes)

    # Print recipe names
    for recipe in recipes:
        print(f"- {recipe.get('name', 'Unknown Recipe')}")


if __name__ == "__main__":
    main()
