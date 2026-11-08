# SOP spec format

`scripts/build_sop.py` takes one JSON file and writes the .docx. This page lists every field and block. `assets/example_spec.json` is a complete worked example (the Ligation sequencing gDNA-Native Barcoding SOP) and is the quickest way to see how real content maps onto blocks.

## Contents
1. Top-level fields
2. Steps
3. Block types
4. Inline text markup
5. Layout behaviour you get for free

## 1. Top-level fields

```json
{
  "title": "Ligation sequencing gDNA-Native Barcoding",
  "header_title": "optional shorter title for the page header",
  "footer": {
    "lab": "For NGS core lab",
    "drafted_by": "Maame Esi Mpere",
    "reviewed_by": "Joyce Ngoi",
    "approved_by": "optional",
    "version": "optional, e.g. 1.0",
    "effective_date": "optional",
    "review_date": "optional (printed as 'Next review')",
    "lines": ["optional extra footer lines, printed last"]
  },
  "purpose": "text, or a list of paragraphs/blocks",
  "scope": "text, or a list of paragraphs/blocks",
  "front_matter": [ {"heading": "Safety", "content": [ ...blocks or strings... ]} ],
  "steps": [ ...see section 2... ],
  "back_matter": [ {"heading": "References", "content": [...], "new_page": false} ],
  "options": {
    "paper": "A4",
    "first_step_new_page": true,
    "steps_new_page": false,
    "letter_sections": true,
    "number_steps": true
  }
}
```

- `title` is required. It is printed in the page header (centred, bold, 14 pt, with a rule under it), not in the body. That is how the reference SOP does it.
- Footer lines print in this order: lab, Drafted by, Reviewed by, Approved by, Version, Effective date, Next review, then `lines`. Leave a key out to drop its line.
- `purpose` and `scope` render as bold "Purpose" / "Scope" headings with the text below. `front_matter` adds more sections after them in the same style (Safety, Definitions, Abbreviations, Responsibilities and so on).
- `back_matter` sections come after the last step (References, Appendix, Revision history).
- Options:
  - `paper`: `"A4"` (default, matches the reference) or `"Letter"`.
  - `first_step_new_page`: Step 1 starts on a fresh page so page 1 holds only the front matter (reference behaviour). Default true.
  - `steps_new_page`: start every step on a new page. Default false. A single step can also set `"new_page": true`.
  - `letter_sections`: sub-stages inside a step get A., B., C. Default true.
  - `number_steps`: banners read "Step N: Title". Default true.

## 2. Steps

```json
{
  "title": "DNA Repair and End-preparation",
  "intro": "This step repairs damaged genomic DNA and prepares the ends for ligation.",
  "new_page": false,
  "content": [ ...blocks... ]
}
```

- The banner text is built as `Step N: <title>`. If the draft title already starts with "Step 3:" or "Step3 -", that prefix is stripped so it is not doubled.
- `intro` is the one or two sentences of purpose that sit directly under the banner. String or list of strings.
- `content` is an ordered list of blocks (section 3).

## 3. Block types

Every block is an object with a `type`. Blocks can appear in step `content`, in `front_matter`/`back_matter` content, and inside a procedure's `steps` list (where they sit between numbered items without breaking the numbering).

### materials
"Materials Required" heading and the three-column table (grey header, bulleted lists in each cell).
```json
{"type": "materials",
 "consumables": ["Filtered pipette tips", "1.5 mL DNA LoBind tubes"],
 "reagents": ["AMPure XP beads", "Elution Buffer (EB)"],
 "equipment": ["Magnetic rack", "Qubit fluorometer"]}
```
Optional: `"heading"` (default "Materials Required", `null` to hide), `"other": {"Software": ["MinKNOW"]}` for extra columns, `"columns": [{"label": "...", "items": [...]}]` to replace the three defaults, `"empty_text"` for an empty column (default "None").

### reagent_prep
"Preparation of reagents" heading and the Item / Storage / Instruction table.
```json
{"type": "reagent_prep", "rows": [
  ["AMPure XP beads", "2°C to 8°C", "Thaw at room temperature. Vortex to mix."],
  {"item": "Ethanol (80%)", "storage": "Room temperature", "instruction": "Freshly prepare."}
]}
```
Optional `"heading"`.

### procedure
Numbered steps 1, 2, 3 under a bold "Procedure" heading. Numbering restarts at 1 for each procedure block.
```json
{"type": "procedure", "steps": [
  "Plain step text.",
  {"text": "Step with sub-steps:", "substeps": ["first bullet", "second bullet",
                                                {"text": "bullet", "substeps": ["deeper"]}]},
  {"type": "table", "layout": "compact", "header": ["Component", "Volume"], "rows": [["Buffer", "10 µL"], ["Total", "10 µL"]]},
  {"type": "note", "text": "Embedded blocks keep the numbering going."},
  "This step is numbered 3."
]}
```
- Sub-steps render as bullets under the step (level 2 is a hollow bullet).
- A step directly followed by a table or image is kept on the same page as it.
- `"heading": null` hides the "Procedure" heading (useful when a section title already says what follows, as in Step 8 of the example).
- `"continue": true` carries numbering on from the previous procedure block in the same step instead of restarting.

### section
A sub-stage inside a step: bold, lettered A., B., C. (letters restart in each step). Use it for things like "gDNA Clean-up", "Post-Ligation Clean-up", "Flow Cell Priming", or "Part A / Part B" in a draft.
```json
{"type": "section", "title": "Post-Ligation Clean-up", "intro": "Remove excess adapters."}
```
`"lettered": false` drops the letter for one section.

### table
General data table: reaction mixes, thermocycler programs, dilution worksheets, acceptance criteria, lookup tables.
```json
{"type": "table",
 "caption": "Recommended centrifugation speed for each input mass",
 "layout": "full",
 "header": ["Sample ID", "Conc. (ng/µL)", "Total input (ng)"],
 "rows": [["A1", "100", "400"], ["A2", "60", "400"]]}
```
- `layout`: `"full"` (page width, default) or `"compact"` (sized to its content and centred, as the reference does for master mixes, thermocycler programs and pooling volumes). `width_cm` fixes a compact table's width.
- Column widths are fitted to the content automatically. Override with `"widths": [3, 1, 1]` (relative weights).
- `caption` prints above the table as "**Table N:** text", numbered through the document. Captions that already start "Table 3:" keep their own number. `"numbered": false` prints the text as is. Only give a caption when the draft has one or the table is referred to by number.
- Multi-row headers: make `header` a list of rows. Any cell can be an object `{"text": "Targeted size", "span": 4}` to span columns.
- Cell objects also take `"bold": true` and `"align": "center" | "right"`. `"align": ["left", "center"]` on the table sets per-column alignment.
- A last row whose first cell starts with "Total" is bolded. Force with `"total_row": true/false`.
- `"first_col_bold": true` bolds the first column (row labels). `"header_fill": "BFBFBF"` changes the header grey. `"valign": "center"` vertically centres cells.
- Tables of up to 15 rows are kept on one page. `"keep_together": false` lets a short table split.

### note, important, caution, safe_stop
Callouts. Each takes `text` and/or `items` (bullets), plus an optional `label`.
```json
{"type": "note", "text": "The diluted control can be stored at -20°C."}
{"type": "important", "text": "Prepare the wash mix fresh for each use."}
{"type": "caution", "text": "Do not vortex the prepared Flow Cell Wash Mix."}
{"type": "caution", "label": "Precaution", "text": "Do not withdraw more than 20 to 30 µL."}
{"type": "safe_stop", "text": "The purified barcoded DNA may be stored at 4°C overnight."}
{"type": "safe_stop", "label": "Safe stopping point and storage", "items": ["4°C short term", "-80°C long term"]}
```
- note: bold "Note:" label.
- important: bold "Important:" label.
- caution: label and text in dark red. Use for anything that damages samples, flow cells or equipment, or is a safety risk.
- safe_stop: yellow highlight, as in the reference.

### heading, paragraph, bullets
```json
{"type": "heading", "text": "Thermocycler program"}
{"type": "paragraph", "text": "Free text.", "align": "left"}
{"type": "bullets", "heading": "optional", "items": ["one", {"text": "two", "items": ["two a"]}]}
```

### troubleshooting
```json
{"type": "troubleshooting", "issues": [
  {"problem": "Sample liquid is stuck in the upper chamber",
   "cause": "Particulate matter is blocking the orifice.",
   "action": ["Repeat the first spin.", "If the block persists, invert and spin."]},
  {"problem": "Low recovery volume",
   "cause": "Cap not tight.",
   "action": "Single-paragraph corrective action."}
]}
```
Issues are numbered and bold, "Cause:" and "Corrective action:" are bold labels, and a list of actions becomes A., B., C.

### image
```json
{"type": "image", "path": "figures/flowcell.png", "width_cm": 12, "caption": "MinION flow cell ports"}
```
PNG or JPEG. Paths are relative to the spec file. Captions print below as "**Figure N:** text".

### page_break
`{"type": "page_break"}`

## 4. Inline text markup

Any text field accepts:

| Markup | Result |
|---|---|
| `**text**` | bold |
| `*text*` | italic (species names, worksheet titles) |
| `***text***` | bold italic |
| `==text==` | yellow highlight |
| `^{2}` | superscript, e.g. `10^{6} cells` |
| `_{2}` | subscript, e.g. `MgCl_{2}` |
| `\*` | a literal asterisk |

Unpaired markers print as plain characters, so a stray `*` will not italicise the rest of a line. Write `<`, `>`, `&`, `°`, `µ`, `≤` directly; the script escapes them.

## 5. Layout behaviour you get for free

- Gill Sans MT 11 pt body, justified; table text left-aligned.
- Step banners are navy bars (fill 153D63, white bold text) set as outline level 1, so they show in Word's navigation pane. Sub-stages are level 2 and headings level 3.
- Banners, headings, captions and lead-in steps keep with what follows, so nothing is stranded at a page bottom.
- Table header rows repeat when a table runs over a page.
- A small gap follows every table.
- Footer: page number on the right, a rule, then the sign-off lines in italic 10 pt.
- Styles are named "SOP ..." in Word (SOP Heading, SOP Procedure Step, SOP Note and so on), so a later manual edit can reuse them.
