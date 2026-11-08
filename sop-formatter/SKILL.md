---
name: sop-formatter
description: Formats laboratory SOPs (standard operating procedures, lab protocols, bench protocols, workflows) into the NGS core lab house style taken from the "Ligation sequencing gDNA-Native Barcoding" SOP, and outputs a Word .docx. Use whenever the user wants an SOP or protocol drafted, cleaned up, restyled, standardised or "put in our SOP format", whether the draft arrives as a .docx, PDF, pasted text, notes or a manufacturer protocol, even if they don't mention the template or say "format".
---

# SOP formatter (NGS core lab house style)

This skill turns a draft SOP into a Word document that matches the lab's reference SOP: title in the page header over a thin rule, Purpose and Scope on page 1, navy "Step N:" banners, grey-headed Materials Required and Preparation of reagents tables, numbered procedures, bold Note labels, yellow safe stopping points, and the "For NGS core lab / Drafted by / Reviewed by" sign-off in the footer of every page.

The work splits into two parts. You read the draft and express its content as a JSON spec. `scripts/build_sop.py` then renders that spec, so the styling comes out identical every time and you never hand-build Word XML.

## Workflow

1. **Read the draft.** For a .docx, call Read on the file (or `pandoc -t markdown draft.docx`). For a PDF, use the pdf-reading approach. Pasted text works as it is. If the draft contains images the user wants kept, unzip the .docx and pull them from `word/media/`.

2. **Collect the footer details.** The footer needs the lab line (default "For NGS core lab"), who drafted it and who reviewed it. Use what the draft or the user gives you. If a name is missing, ask once; if the user isn't around, leave that key out and say so at the end rather than inventing a name.

3. **Map the content onto the structure** (see "How draft content maps" below) and write the spec to a working file, e.g. `spec.json`. `references/spec_format.md` documents every field and block; `assets/example_spec.json` is the reference SOP itself in spec form, so copy its patterns.

4. **Check, then build:**
   ```bash
   python scripts/build_sop.py spec.json --check      # validates and prints the outline
   python scripts/build_sop.py spec.json -o "<SOP title>.docx"
   ```
   `--check` errors name the exact spot (for example `steps[3].content[2]: missing 'rows'`). Read the outline it prints against the draft to confirm nothing was dropped: every step, sub-stage and table should be there.

5. **Look at the result.** Render and read the page images:
   ```bash
   soffice --headless --convert-to pdf "<SOP title>.docx"
   pdftoppm -r 70 -png "<SOP title>.pdf" page
   ```
   Check for tables split from the step that introduces them, columns too narrow for their text, and content that ended up in the wrong step. LibreOffice substitutes another font for Gill Sans MT, so line breaks shift slightly in Word; that is expected.

6. **Deliver the .docx** and, in a few lines, list what you changed beyond formatting (see "Content rules") and anything you need from the user, such as a missing reviewer name.

## How draft content maps

Most drafts already follow the reference structure loosely. Match each piece of the draft to the closest element:

| Draft content | Spec element |
|---|---|
| Title of the protocol | `title` (shown in the header on every page) |
| Purpose / Aim / Objective | `purpose` |
| Scope / Applicability | `scope` |
| Safety, Definitions, Abbreviations, Responsibilities | `front_matter` sections |
| Each major stage (QC, shearing, end-prep, ligation, sequencing, wash...) | one entry in `steps` |
| The sentence saying what the stage is for | the step's `intro` |
| Consumables / reagents / equipment lists | `materials` |
| Storage temperature and thaw/mix instructions | `reagent_prep` |
| Numbered or sequential instructions | `procedure` |
| A named sub-stage within a stage ("gDNA clean-up", "Part A", "Flow cell priming") | `section`, followed by its own blocks |
| Master mix, thermocycler program, pooling or dilution tables | `table` with `"layout": "compact"` |
| Wide data tables, acceptance criteria, lookup grids | `table` (full width) |
| Note / Tip | `note` |
| Important | `important` |
| Warning, Caution, Precaution, "Do not ..." that protects samples, flow cells or people | `caution` |
| Safe stopping point / storage pause | `safe_stop` |
| Problem / cause / fix | `troubleshooting` |
| References, appendices, revision history | `back_matter` |

Some judgement calls:
- A note, table or warning that sits between numbered steps goes inside the procedure's `steps` list, so the numbering carries on around it instead of restarting.
- One stage of work is one step. If the draft has a "Step 3a" and "Step 3b", those are usually sections within Step 3.
- If a stage needs different materials for a sub-stage (as with the post-ligation clean-up in the reference), put a `section` and then a second `materials` and `reagent_prep` under it.
- Material lists in a draft are often run together in one line or one cell. Split them into one item per consumable, reagent or instrument.
- Drop empty spacer paragraphs, manual numbering ("1.", "a)") and hand-typed bullet characters. The script numbers and bullets everything itself.
- Use `**bold**` for the warnings and key values the author emphasised ("**Do not pellet the beads.**", "**within 15 minutes**"). Don't add new emphasis.

## Content rules

The SOP belongs to the lab, so keep the author's wording and technical content. Formatting is the job.

Fine to change, and list in your summary:
- obvious typos ("Quantity samples" to "Quantify samples", "upto" to "up to");
- consistent units and spacing (µL rather than µl/ul, "600 ng", "°C", "x g");
- consistent capitalisation of reagent names and labels, and "Step1" to "Step 1";
- cross-references that the new numbering would otherwise break ("repeat steps 8 to 9" must still point at the right steps after renumbering; recheck these).

Not fine without asking:
- changing volumes, concentrations, times, temperatures, speeds, kit codes or the order of steps;
- adding steps, materials or safety content that isn't in the draft;
- deleting content you think is redundant.

If something looks wrong (a total that doesn't add up, a step that contradicts another, a missing reagent in the materials table), keep it as written and point it out to the user.

When you have to write a short connecting sentence the draft lacks, such as a missing step intro, keep it plain and in the author's voice, avoid em dashes, and mention it in your summary.

## Files

- `scripts/build_sop.py`: the renderer (Python 3, standard library only).
- `references/spec_format.md`: full spec reference. Read it when you need a block option not shown in the example.
- `assets/example_spec.json`: the reference SOP as a spec, covering every block type except images. Build it with `python scripts/build_sop.py assets/example_spec.json -o example.docx` to see the target look.
