import sys
import argparse
from pathlib import Path
from jinja2 import Template
import json


def slugify(text):
    if not text:
        return "unnamed-recipe"
    return text.lower().replace(" ", "-").replace("_", "-")


def main():
    # Mock data
    mock_recipes = [
        {
            "id": "1",
            "name": "Test Pancake",
            "image": "test-pancake.webp",
            "description": "Delicious mock pancakes",
            "recipeIngredient": [
                {"display": "Flour"},
                {"display": "Milk"},
                {"display": "Eggs"},
            ],
            "instructions": ["Mix", "Fry", "Eat"],
        },
        {
            "id": "2",
            "name": "Mock Salad",
            "image": "mock-salad.webp",
            "description": "Fresh mock salad",
            "recipeIngredient": [{"display": "Lettuce"}, {"display": "Tomato"}],
            "instructions": ["Wash", "Chop", "Mix"],
        },
    ]

    script_dir = Path(__file__).parent
    parent_dir = script_dir.parent

    # 1. Create recipes dir
    recipes_dir = parent_dir / "recipes"
    recipes_dir.mkdir(exist_ok=True)

    # 2. Generate recipe pages
    recipe_template_path = script_dir / "templates" / "recipe.html"
    with open(recipe_template_path, "r", encoding="utf-8") as f:
        recipe_template = Template(f.read())

    for recipe in mock_recipes:
        html_content = recipe_template.render(recipe=recipe)
        slug = slugify(recipe["name"])
        with open(recipes_dir / f"{slug}.html", "w", encoding="utf-8") as f:
            f.write(html_content)

    # 3. Generate index
    index_template_path = script_dir / "templates" / "index.html"
    with open(index_template_path, "r", encoding="utf-8") as f:
        index_template = Template(f.read())

    html_index = index_template.render(recipes=mock_recipes)
    with open(parent_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(html_index)

    print("Mock export completed successfully.")


if __name__ == "__main__":
    main()
