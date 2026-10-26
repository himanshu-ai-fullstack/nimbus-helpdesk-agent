"""Scaffold a new tenant folder.

    uv run python -m app.tenants.new acme --name "Acme Robotics" --industry "robot vacuum maker"

Creates tenants/<slug>/ with a tenant.yaml to edit, a sample help article and an
empty data.json, validates it, and prints the next steps. Restart the API (or
run the seed) to load it.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from .loader import TENANTS_DIR, load_tenant
from .models import SLUG

TEMPLATE = {
    "industry": "",
    "tagline": "Orders, accounts and product help",
    "brand_color": "#2563eb",
    "persona": "Ava",
    "audience": "customers",
    "greeting": "",
    "prompt": "Describe anything the agent must always or never do for this company.\n",
    "suggestions": ["How do I get started?"],
    "actions": {
        "refund": {
            "label": "Refund",
            "description": "Refund a paid order after confirming the order and amount.",
            "record_type": "order",
            "require_status": ["paid"],
            "window_days": 30,
            "max_amount_usd": 100,
            "cap_to_remaining": True,
        }
    },
    "triage": {
        "categories": ["billing", "account", "product_issue", "how_to", "other"],
        "priority_guide": "urgent = security or data loss; high = blocked; "
        "medium = degraded; low = questions.",
    },
    "display": {
        "account_label": "Customer",
        "account_fields": {},
        "record_labels": {"order": "Order"},
    },
}

SAMPLE_DOC = """# Getting started with {name}

Replace this article with your own help-center content. Each Markdown file in this
folder becomes a searchable, citable article; start it with a `# Title` line.
"""


def scaffold(slug: str, name: str, industry: str, root: Path = TENANTS_DIR) -> Path:
    if not SLUG.match(slug):
        raise ValueError("slug must be lowercase letters, digits and dashes, 2-31 characters")
    folder = root / slug
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    config = {
        "name": name,
        **TEMPLATE,
        "industry": industry,
        "greeting": f"I'm the support assistant for {name}. How can I help?",
    }
    (folder / "docs").mkdir(parents=True)
    (folder / "tenant.yaml").write_text(yaml.safe_dump(config, sort_keys=False, width=88))
    (folder / "docs" / "getting-started.md").write_text(SAMPLE_DOC.format(name=name))
    (folder / "data.json").write_text(json.dumps({"accounts": [], "records": []}, indent=2) + "\n")
    load_tenant(folder)  # fail now, not at startup
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new tenant folder.")
    parser.add_argument("slug")
    parser.add_argument("--name", required=True)
    parser.add_argument("--industry", required=True)
    args = parser.parse_args()
    try:
        folder = scaffold(args.slug, args.name, args.industry)
    except (ValueError, FileExistsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"Created {folder}\n"
        "Next: edit tenant.yaml (persona, prompt, actions, triage), add docs/*.md and "
        "data.json,\nthen run `uv run python -m app.tenants.seed "
        f"{args.slug}` and add an admin token to TENANT_ADMIN_TOKENS."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
