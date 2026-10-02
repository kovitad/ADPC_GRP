# Sharing flood-preparedness data with the Global Risk Platform

A hands-on guide for Claude Desktop and Claude Cowork. For Hub staff and business users who want
to add a dataset to the Global Risk Platform, check that it landed, see what it changes in the
answers, and follow it through to the district summary a planner downloads from GRP.

## What you will do

1. Find the dataset's Google Drive link in the links sheet.
2. Ask Claude to submit it with `contribute_submit`.
3. Read the reply: approved, staged for review, or declined with the reasons.
4. Check it with `contribute_status`.
5. Ask a question that uses it, and compare the answer with GRP's numbers.
6. In GRP, gather Global Risk evidence again and download the district's Word summary.

Each dataset takes about ten minutes. Steps 5 and 6 take another ten.

> **Important:** Global Risk may approve your contribution automatically. The first reply tells
> you which (Step 3). If it says `approved`, **every user** of the platform sees the layer in
> their answers at once, and only a Global Risk reviewer can remove it. So **one named person
> submits each dataset, once**. Everyone else follows the steps up to Step 2 and stops before
> sending, then does Steps 4 to 6 to see the result. Ask the GRP team who submits which dataset.

## The layer name is the key

> **Remember:** refer to every dataset by its layer name, exactly as the manifest writes it. Use
> it when you submit, when you check, when you ask a question and when you ask for a removal.
> Never change it.

Every dataset has a name: the `layer:` line in its manifest, or `dataset:` for a table, for
example `early_warning_towers_ddpm`. **That name is how everyone refers to the data.**

- **Global Risk counts and cites by the name.** Answers say "N of M early_warning_towers_ddpm …".
- **Removal is by the name.** The Global Risk team removes a layer by its name.
- **GRP's Word summary recognises GRP's data by the name.** A renamed layer would read as "Not in
  GRP's data".
- **Contributions never overwrite.** Submitting under a new name, such as `_v2` or a typo, does
  not replace anything. It adds a second copy, and every answer then counts both.

So:

1. **Keep every name exactly as written in the manifest.** Never rename, shorten or add to it.
2. **Name the layer in every question you ask** ("Using the layer early_warning_towers_ddpm, …")
   and ask Claude to say which layers it counted.
3. **Keep the contribution_id as well.** The name identifies the data; the ID identifies one
   submission. You never send the ID back to submit or update. You use it to check the record
   (Step 4), to withdraw a staged one yourself, or to tell the GRP team which one to remove.
4. **To replace a layer with a corrected file,** give the GRP team both keys ("layer
   `villages_th_register`, contribution `<id>`"). They have Global Risk remove it, then you
   submit the new file once, under the same name.

Each folder's `TEST.md` starts with its layer name and uses it in every step.

GRP enforces this too. Its **Share data** page refuses a layer name that is already on Global
Risk, and says why in a pop-up: Global Risk cannot update a contribution. GRP learns of a layer
sent from Claude Desktop only once a Planning lookup has counted it.

## Before you start

- **Claude Desktop or Claude Cowork** with the **SERVIR Global Risk** connector switched on, signed
  in with your own account. To check, ask Claude: "Which SERVIR Global Risk tools can you use?"
  The list should include `contribute_submit` and `contribute_status`.
- **The shared Google Drive folder from the GRP team** (`google-drive-upload`). It has one
  numbered folder per dataset, each with the data file, a ready-made request (`manifest.yaml`)
  and a test sheet (`TEST.md`), plus `LINKS.csv`, the links sheet.
- **For Step 6, a GRP account with the planner role** in your Hub. Your Claude Desktop answers do
  not reach GRP: the summary uses only the evidence gathered under your own GRP sign-in.
- Do not submit raw shapefiles or spreadsheets: they must be converted first, and contact details
  removed. The files in the folder already are.

## The datasets, in the order to submit them

| Folder | Layer name | Submit? |
|---|---|---|
| 01_early_warning_towers | `early_warning_towers_ddpm` | Yes |
| 02_volunteer_centres | `civil_defence_volunteer_centres_ddpm` | Yes |
| 03_villages | `villages_th_register` | Yes |
| 04_OPTIONAL_population_grid | `population_th_village_register` | Only if the GRP team says so (experimental) |
| 05_OPTIONAL_subdistrict_population_table | `th_subdistrict_population` | Only if the GRP team says so |
| 06_OPTIONAL_flood_thailand_rp100 | `hazard_flood_thailand_rp100` | Only if the GRP team says so |
| HOLD_evacuation_centres_until_test_layer_withdrawn | `evacuation_centres_ddpm` | **No, not yet** |

The evacuation centres wait because an older test copy of the same 10,303 centres is still in
Global Risk. Submitting again now would make every answer count them twice. The GRP team will
tell you when the old copy has been withdrawn.

## Step 1: Find the link

1. Open `LINKS.csv` in the shared folder and find the dataset's row. Its link looks like
   `https://drive.google.com/file/d/1AbC...xyz/view?usp=sharing`.
2. If the row has no link yet, open the dataset's folder in Google Drive, right-click the data
   file, choose **Share**, check that **General access** is **Anyone with the link**, and click
   **Copy link**.

Use the link to the **file**, not the folder: a folder link returns a web page, not your data.

## Step 2: Ask Claude to submit it

Open the dataset's `manifest.yaml` and paste it into Claude with a request like this, using your
own link:

```text
Please submit this to the Global Risk Platform with contribute_submit.
Change my Google Drive link to its direct-download form first and put it in url.
My link: https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing

kind: vector
layer: early_warning_towers_ddpm
url: https://drive.google.com/uc?export=download&id=<FILE_ID>
title: Early-warning towers and equipment, Thailand (DDPM)
description: One point per DDPM early-warning resource (1,533), mostly warning towers, with the site name and administrative area.
source: Thailand DDPM, compiled by ADPC
license: unstated
vintage: "2026-09"
countries: [Thailand]
name_field: name
```

The direct-download form is `https://drive.google.com/uc?export=download&id=<FILE_ID>`, where
`<FILE_ID>` is the long code between `/d/` and `/view` in your link. Claude can make the change
for you, as in the request above.

## Step 3: Read the reply

The reply is one of three kinds. Write the time, the `contribution_id` and the state in
`LINKS.csv` whichever it is.

- **approved: auto-approve is on.** The reply names the layer and gives the number of
  features. The layer is now public to every Global Risk user and cited as "auto-approved — no
  human reviewed this layer". You cannot take it back; only a Global Risk reviewer can.
- **staged, pending or preview: auto-approve is off.** The layer is stored for review. Only
  you and the Global Risk reviewers see it, and answers cite it with a PREVIEW note. It becomes
  public only when a reviewer approves it. Until then you can test it (Steps 4 to 6) and, if it
  is wrong, take it back yourself by asking Claude: "Use contribute_status with action withdraw
  and contribution_id `<your id>`." Once withdrawn, you may submit the corrected file under the
  same name.
- **declined: nothing landed.** The reply lists every problem at once, with the fields it
  expects. The usual causes are a folder link, a file that is not shared, or a missing field.
  Fix it and submit again under the same name. This is the only reply after which you submit the
  same dataset again straight away.

## Step 4: Check it by name

```text
Use contribute_status and show me my contributions. Is early_warning_towers_ddpm there, and what is its state?
```

Find the row with your layer name. It should read `approved` with the reviewer shown as
auto-approve, or staged, waiting for a reviewer. Either is an honest record of how it landed.

## Step 5: Ask a question that uses it

Each folder's `TEST.md` has the question to ask and GRP's own numbers to compare. For example:

```text
Using the layer early_warning_towers_ddpm, how many early-warning towers in Tha Pla District, Uttaradit sit in the 100-year flood hazard, by severity? Name the layer you counted and the area of the district polygon you used.
```

The answer should cite your layer **by its name**, with a line such as "N of M
early_warning_towers_ddpm in Tha Pla District fall in flood hazard class 1 or higher …
auto-approved" (or PREVIEW if it is staged). If it cites a different layer or none, ask again
and name the layer. Write its numbers beside GRP's in the table under "Results sheet" below.

## Step 6: Follow it into the planner's district summary in GRP

This is the end-to-end check: does the new layer reach the Word document a planner downloads?

1. Sign in to GRP and open **Planning**.
2. Select the district you asked about in Step 5, for example Samko, Ang Thong.
3. Run the flood assessment, then click **Add Global Risk context**.
4. **If your contribution is staged, not approved,** only the SERVIR account that submitted it
   can see it. The GRP user in this step must be signed in to SERVIR with that same account, or
   the new layer will not appear.
5. **If the evidence card says "reused, no new Global Risk lookup",** GRP has reused evidence
   you gathered in the last hour, which does not have your new layer. Click **Gather again from
   Global Risk** on that card.
6. Read the brief in the chat. It usually names the layers Global Risk counted. The Word summary in step 8 is the definite check.
7. Click **Download summary** at the top of the page to get the district's Word document.
8. Open section **5. Global Risk evidence** and make the checks below.

In section 5 of the Word summary, check that:

- the grey note names Global Risk's flood layer and the area of its district polygon;
- the table "What Global Risk adds for this district" has a row for the new layer, with the
  **layer name in brackets**, for example "Early-warning towers (early_warning_towers_ddpm)";
- that row says "GRP's own data, counted again by Global Risk; not an independent check";
- schools, hospitals, buildings and roads say "Not in GRP's data; Global Risk adds it".

If the new layer is missing, note the time and the evidence pack number printed at the top of
section 5 and send them to the GRP team.

## Step 7: Ask about exactly the layers you choose

Once Step 6 has counted your layer, GRP lists it in the Planning layer picker.

1. In **Planning**, select the district or sub-district.
2. Above the message box, open **Global Risk layers** and tick the layers you want, for example
   your new layer and Schools. Each shows its label and its exact name.
3. Click **Write the question**. GRP writes a precise question naming the area and every chosen
   layer. For a sub-district it asks about the district that contains it, because Global Risk
   counts whole districts, and says so. You can edit the question before sending it.
4. Send it. While layers are ticked, every Global Risk question uses them. Click **Clear** to go
   back to all layers.
5. The evidence card, and section 5 of the downloaded Word summary, show only the chosen layers,
   with the note "Layers chosen for this question". A chosen layer Global Risk returned no count
   for says so instead of disappearing.

## Results sheet

Copy this table into your notes, or fill in the matching columns in `LINKS.csv`. GRP's numbers
come from the official DOPA district boundary and GRP's own flood tiles.

| Layer | Samko: Global Risk / GRP | Tha Pla: Global Risk / GRP | In the Word summary? |
|---|---|---|---|
| early_warning_towers_ddpm | ___ / 0 of 0 | ___ / 0 of 11 | |
| civil_defence_volunteer_centres_ddpm | ___ / 4 of 4 | ___ / 2 of 10 | |
| villages_th_register | ___ / 25 of 33 | ___ / 8 of 76 | |
| population_th_village_register | ___ / 12,633 of 16,571 people | ___ / 3,927 of 38,316 people | |
| hazard_flood_thailand_rp100 | ___ / 8 of 12 centres | ___ / 0 of 13 centres | |

Record the submit time, `contribution_id` and status in `LINKS.csv`.

For volunteer centres, Bang Bua Thong, Nonthaburi is a good extra district: GRP finds 8 of 8 in
the flood area.

## Questions you can ask any time

None of these add data or change anyone else's answers. Try them before and after a contribution to see what changes. The first two only look things up. A risk question may end with a public receipt, a link that lets anyone replay the answer and its evidence. That is normal, so do not put personal details in a question.

```text
Use platform_capabilities: which layers does Global Risk hold for Thailand, and which were contributed?
```

```text
Use contribute_status and show me my contributions and their state.
```

```text
Using the Global Risk risk pack, what is exposed in the 100-year flood in Samko District, Ang Thong: schools, hospitals, buildings, roads, and any contributed layers? Show counts by severity and name every layer you counted.
```

```text
How old is each source behind that answer, which were pulled live, and what is missing?
```

```text
How many people in Bang Bua Thong District, Nonthaburi live in the 100-year flood zone? Which population layer did you use?
```

```text
Why might your count of evacuation centres in Tha Pla District differ from a count made with the official DOPA district boundary?
```

## Example: a map layer (raster)

Rasters follow the same steps. The manifest also declares the legend and the value range, and
Global Risk checks the file against them:

```text
kind: raster
layer: hazard_flood_thailand_rp100
url: https://drive.google.com/uc?export=download&id=<FILE_ID>
title: Flood depth, 1-in-100 year, Thailand (JRC tiles, reclassed 1-5)
description: 100-year flood depth reclassed to five depth bands; 0 means dry or no data.
source: JRC Global Flood Hazard Maps (RP100 depth tiles), as delivered to ADPC
license: unstated
vintage: "2026-09"
legend: {"1": "Very low (<= 0.5 m)", "2": "Low (0.5-1 m)", "3": "Moderate (1-1.5 m)", "4": "High (1.5-2 m)", "5": "Very high (> 2 m)"}
declared: {"dtype": "uint8", "valid_min": 0, "valid_max": 5, "nodata": 0}
```

Then ask:

```text
Using the layer hazard_flood_thailand_rp100, how many evacuation centres in Samko District are exposed?
```

GRP's Planning page always asks Global Risk about its standard flood layer, so this layer shows
up in Claude's answers but not in GRP's Word summary.

## Do and don't

- **Do** submit only the prepared files. They have contact details removed and have passed GRP's
  checks.
- **Do** write down each `contribution_id` and the time you submitted.
- **Do** ask the follow-up question for two districts and note the numbers beside GRP's.
- **Don't** submit anything from the HOLD_ folder until the GRP team says so.
- **Don't** submit a dataset again once it is approved, even to "try again" or to send a
  corrected file. Global Risk's runbook says contributions never overwrite existing entries, so a
  repeat cannot replace the first copy. To replace a layer, the Global Risk team must first remove
  the old one. If a submit seems stuck, run `contribute_status` before doing anything else.
- **Don't** submit files with names, telephone numbers, e-mail or LINE IDs of people.
- **Don't** submit the same data twice under different layer names: Global Risk would count both.
  Ask the GRP team which layers are already there.
- **Don't** submit **weights** unless the data owner has agreed them. Never submit weights for the
  hazard `flood`: that changes every user's risk levels for Thailand.
- **Don't** expect to take a contribution back yourself. Once approved, only a Global Risk
  reviewer can withdraw it. Tell the GRP team if something went in by mistake.

## When the numbers differ from GRP

They often will, for reasons that are not mistakes:

- **Different district shapes.** Global Risk draws districts from OpenStreetMap; GRP uses the
  official DOPA boundaries. Tha Pla is 1,784 km² in Global Risk and 1,154 km² in GRP.
- **Different flood maps.** Global Risk's own 100-year flood layer is not the same file GRP uses.
  In Samko, GRP finds 8 of 12 centres in the flood area; Global Risk said 12 of 12.
- **"No data" is not "safe".** Where the flood map has no value, GRP says "N/A — unable to
  assess". Global Risk counts it as not exposed.
- **Counts, not names.** Global Risk says how many, never which ones. Use GRP to see which
  centres.
- **Villages, not people.** Global Risk counts villages as points. It adds up people only from a
  population grid (folder 04).

Write down what you see. The GRP team uses these notes to decide what to fix and what to ask the
Global Risk team.

## If something goes wrong

| What you see | What to do |
|---|---|
| "The link returned a web page" | Use the file's link, not the folder's, shared with "Anyone with the link". |
| Declined: a field is required | Add the named field; the reply lists them all. |
| Declined: values outside the declared range | The file does not match its manifest. Send the reply to the GRP team. |
| Approved, but the answer does not mention the layer | Wait a minute and ask again, naming the layer in your question. |
| The reply says staged, pending or preview | Auto-approve is off. Test it; withdraw it yourself if it is wrong (Step 3). |
| A layer went in under the wrong name | Tell the GRP team the wrong name and its `contribution_id`. Do not submit it again under the right name until the wrong one is removed. |
| The Word summary does not show the new layer | Click **Gather again from Global Risk** in GRP, then download again. |
| GRP says to sign in with SERVIR again | Sign in again from the Planning page, then repeat Step 6. |
| Claude says it cannot find `contribute_submit` | Switch on the SERVIR Global Risk connector and sign in again. |
