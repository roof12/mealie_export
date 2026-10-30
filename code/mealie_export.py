#!/usr/bin/env python
import sys
import argparse
import requests
import json
from jinja2 import Template
from pathlib import Path


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


def fetch_images(base_url, api_key, recipes):
    """Fetch images for recipes where the image field is an ID rather than a URL."""
    from urllib.parse import urlparse

    # Determine the parent directory (where the script's parent directory is)
    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for recipe in recipes:
        image_value = recipe.get("image")
        if image_value:
            # Check if image_value is a URL by checking if it has a scheme
            parsed = urlparse(image_value)
            if not parsed.scheme:  # If it's not a URL, treat it as an ID
                # Use the recipe's actual ID instead of the image value
                recipe_id = recipe.get(
                    "id", image_value
                )  # Use recipe ID if available, otherwise use image value
                image_url = (
                    f"{base_url}/api/media/recipes/{recipe_id}/images/min-original.webp"
                )

                try:
                    response = requests.get(image_url, headers=headers)
                    response.raise_for_status()

                    # Create a filename based on the recipe name
                    recipe_name = recipe.get("name", "unnamed_recipe")
                    # Sanitize the recipe name for use as a filename
                    sanitized_name = "".join(
                        c for c in recipe_name if c.isalnum() or c in (" ", "-", "_")
                    ).rstrip()
                    if not sanitized_name:
                        sanitized_name = "unnamed_recipe"

                    # Save images in the parent directory (top level)
                    filename = parent_dir / f"{sanitized_name}.webp"

                    with open(filename, "wb") as f:
                        f.write(response.content)

                    # Update the recipe's image field to point to the local file (relative to index.html)
                    recipe["image"] = f"{sanitized_name}.webp"
                    print(f"Downloaded image for recipe '{recipe_name}' -> {filename}")

                except requests.exceptions.RequestException as e:
                    print(
                        f"Error fetching image for recipe '{recipe.get('name', 'Unknown Recipe')}': {e}"
                    )
                    if e.response is not None:
                        print(f"Status code: {e.response.status_code}")


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
