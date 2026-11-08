# My Skills Repository

Custom Claude/OpenCode skills for laboratory workflows and writing. Each skill is a self-contained package of instructions, helper scripts, and resources that Claude can discover and load dynamically to deliver expert-level results.

## Skills

| Skill | Description |
|-------|-------------|
| **[humanizer](humanizer/)** | Rewrites prose to read like a careful person wrote it, not a chatbot. Fixes AI writing tells (em dashes, stock vocabulary, padded phrasing) and enforces personal writing standard. |
| **[gel-labeller](gel-labeller/)** | Labels agarose gel images with sample IDs from a plate map, adds ladder size scales, and calls bands with sizes into a results table. Includes a full Python toolkit with platemap parsing, ladder fitting, QC, and rendering. |
| **[sop-formatter](sop-formatter/)** | Formats laboratory SOPs into the NGS core lab house style and outputs a Word `.docx`. Converts a draft into a JSON spec, then `scripts/build_sop.py` renders it with consistent styling every time. |

## What is a skill?

Skills are organized packages of instructions, executable code, and resources that give Claude specialized capabilities for specific tasks. They load on demand through **progressive disclosure**:

1. **Metadata** — Claude sees the YAML frontmatter (`name` + `description`) from every SKILL.md.
2. **Instructions** — When a skill is relevant, the full SKILL.md and any `.md` files load.
3. **Resources** — Helper scripts, templates, and data files load only when needed during execution.

This keeps the initial context lean while delivering deep expertise on request.

## Directory structure

Every skill follows this layout:

```
skill-name/
├── SKILL.md              # Required: YAML frontmatter + instructions
├── scripts/              # Optional: helper code (Python, etc.)
│   └── main.py
├── references/           # Optional: documentation, specs, guides
│   └── spec.md
├── assets/               # Optional: templates, data files
│   └── example.json
└── tests/                # Optional: test suite
    └── test_main.py
```

The **SKILL.md** is the only required file. It must include:

```yaml
---
name: skill-name
description: Brief description of what the skill does (trigger phrases, scope).
---
```

## Creating a new skill

1. Create a directory: `mkdir my-skill && cd my-skill`
2. Write **SKILL.md** with YAML frontmatter and step-by-step instructions.
3. Add any helper scripts under `scripts/`, references under `references/`, and templates under `assets/`.
4. Commit and push — the skill is discoverable when the repository is loaded.

## Resources

- [Claude Skills documentation](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
- [Skills best practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
- [Teach Claude your way of working](https://support.claude.com/en/articles/12580051)
- [How to create a skill through conversation](https://support.claude.com/en/articles/12599426)
