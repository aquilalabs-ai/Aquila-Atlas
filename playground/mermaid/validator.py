import os
import subprocess
import json
import tempfile
import uuid


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FRONTEND_DIR = os.path.abspath(
    os.path.join(BASE_DIR, "../../frontend")
)

NODE_SCRIPT = os.path.join(FRONTEND_DIR, "src", "mermaid_check.js")

OUTPUT_DIR = os.path.join(BASE_DIR, "diagrams")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def validate_and_render_mermaid(diagram_code: str):
    """
    1. Validate using Node (your working method)
    2. Render SVG using local mmdc (no npx, no PATH issues)

    Returns:
        dict:
        {
            "valid": bool,
            "error": str | None,
            "svg_path": str | None
        }
    """

    # -------------------------
    # 1. VALIDATION (UNCHANGED - your working code)
    # -------------------------
    result = subprocess.run(
        ["node", NODE_SCRIPT, diagram_code],
        capture_output=True,
        text=True,
        cwd=FRONTEND_DIR
    )

    try:
        output = json.loads(result.stdout)
    except Exception:
        return {
            "valid": False,
            "error": result.stderr.strip() or "Unknown error",
            "svg_path": None
        }

    if not output.get("valid"):
        return {
            "valid": False,
            "error": output.get("error", "Unknown error"),
            "svg_path": None
        }

    # -------------------------
    # 2. CREATE TEMP .mmd FILE
    # -------------------------
    file_id = uuid.uuid4().hex[:10]

    with tempfile.NamedTemporaryFile(
        suffix=".mmd",
        delete=False,
        mode="w",
        encoding="utf-8"
    ) as f:
        f.write(diagram_code)
        input_path = f.name

    svg_path = os.path.join(OUTPUT_DIR, f"diagram_{file_id}.svg")

    try:
        # -------------------------
        # 3. RENDER SVG (NO npx)
        # -------------------------
        render = subprocess.run(
            [
                "node",
                os.path.join(
                    FRONTEND_DIR,
                    "node_modules/@mermaid-js/mermaid-cli/src/cli.js"
                ),
                "-i", input_path,
                "-o", svg_path
            ],
            capture_output=True,
            text=True,
            cwd=FRONTEND_DIR
        )

        if render.returncode != 0:
            return {
                "valid": False,
                "error": render.stderr.strip() or "SVG rendering failed",
                "svg_path": None
            }

        return {
            "valid": True,
            "error": None,
            "svg_path": svg_path
        }

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


if __name__ == "__main__":
    result = validate_and_render_mermaid("graph TD; A-->B; B-->C")
    print(result)