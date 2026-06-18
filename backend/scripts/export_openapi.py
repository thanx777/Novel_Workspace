"""导出 FastAPI 应用的 OpenAPI 规范到 JSON 文件。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

def export_openapi(output_path: str = "openapi.json"):
    schema = app.openapi()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    print(f"OpenAPI schema exported to {output_path}")
    print(f"  Paths: {len(schema.get('paths', {}))}")
    print(f"  Schemas: {len(schema.get('components', {}).get('schemas', {}))}")

if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    export_openapi(output)
