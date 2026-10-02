# Share data with Global Risk: step-by-step guide

*Version 1.3 · 30 September 2026 · ADPC GRP team*

For Hub planners who have a prepared dataset and want Global Risk to count and cite it. Every
step is shown two ways:

- **In GRP**: the **Share data** page (`/contribute.html`), which checks your data before
  anything leaves GRP.
- **In Claude Desktop or Cowork**: the matching SERVIR Global Risk tool call, for when you
  work outside GRP.

What the page does: you add your Hub's layers, tables and reports to the Global Risk platform, so
its answers can count and cite them. Global Risk downloads the file itself, checks it against
what you declare, and tells GRP whether it landed.

The ready-made data is in the upload kit, the `google-drive-upload` folder the GRP team shares
with you. Appendix A has the exact value to type in every form field for each dataset in it.

## Pick one route per dataset, and submit once

> **Important:** send each dataset **once**, by **one person**, through **one route**, either
> GRP's Share data page or Claude Desktop, never both. Global Risk contributions never overwrite.
> A second submit, even under the same name, cannot replace the first. A new name adds a second
> copy, and every answer then counts both.

| | GRP Share data page | Claude Desktop |
|---|---|---|
| Checks the fields before sending | Yes, the **Check** button | No, Global Risk checks on submit |
| Refuses a name Global Risk already holds | Yes, with a pop-up | **No**, you must check yourself (Step 4) |
| Refuses point files with phone, fax or e-mail fields | Yes | No |
| Records who sent what, for the Hub | Yes, in the **Contributions** list | No. GRP learns of the layer only once a Planning lookup counts it |
| Withdraw a staged contribution | No button, use Claude Desktop (Step 9) | Yes |

**Use the GRP page unless you have a reason not to.** It has more guards, and your Hub can see
the record.

**Just want to try it? Do not send anything.** This Global Risk deployment approves every
contribution automatically, so anything you send is public at once. "Try it yourself", near
the end, shows how to practise without sending anything, and how to use the test layer the GRP
team has already sent.

## Sending means publishing

This was confirmed on 30 September 2026, with the reply to the GRP team's first test copy:

- **Every contribution is auto-approved.** The reply says: `auto-approved: this deployment lands
  contributions without review`. Its closing line: "it is live for every caller now".
- **It is public at once.** Every Global Risk user's answers count it, for any Thai place it
  covers.
- **Ignore one line of the reply.** Its `how_to_test` text says "only you and reviewers see it
  until it is approved". On this deployment that is not true: it is already approved.
- **Removal is not guaranteed.** Global Risk describes `withdraw` as taking back a *pending*
  contribution, so withdrawing an approved one yourself may be refused. See Step 9.

### "My contributions" means you sent them, not that only you see them

`contribute_status` with no arguments lists only what **your SERVIR account** sent. The rows
are yours to manage, but the layers are **not private**: once approved, they are served to
every user.

### What ADPC has already put on Global Risk

| Layer | Global Risk ID | Points | Sent | What it is |
|---|---|---|---|---|
| `evacuation_centres_th_test` | `c66ade79bc2605ac` | 10,303 | 24 Sep 2026 | TEST copy of the DDPM evacuation centres |
| `early_warning_towers_test_kovitad` | `212436d83e490738` | 1,533 | 30 Sep 2026 | TEST copy of the DDPM early-warning towers |

Both are approved, live and national, and both have the licence `unstated`. Both are marked
TEST in their titles, but they are counted in real answers. **Do not send the real layer for
either dataset until its test copy is withdrawn**, or every answer counts the points twice.

## Before you start

**For the GRP route:**

1. **GRP runs on the local desktop stack.** Open <http://127.0.0.1:8000>. The page only works
   where the planning assistant runs. Anywhere else it says: "Sharing with Global Risk runs only
   where the planning assistant runs".
2. **You need a planning role in a Hub:** planner, NDMO planner, Hub expert or Hub admin. A
   Platform Admin role alone is not enough; the page says "You need a planning role in a Hub".
3. **You must be signed in to SERVIR.** The pill at the top right of **New contribution** reads
   **SERVIR signed in**. If it reads **Sign in with SERVIR to send**, click it and sign in. Every
   GRP rebuild signs you out of SERVIR, so check this each time.

**For the Claude Desktop route:**

1. Claude Desktop or Cowork has the **SERVIR Global Risk** connector switched on and signed in
   with your own account.
2. To check, ask: `Which SERVIR Global Risk tools can you use?` The list must include
   `contribute_submit` and `contribute_status`.

**For both routes:**

1. **The data file must be prepared.** Use only the files in the upload kit: contact details are
   removed and every file has passed GRP's checks. Never send a raw shapefile or spreadsheet.
2. **The file must be reachable by link.** Global Risk downloads the file itself, so it needs a
   public link (Step 1).
3. **Check which folders you may send.** Folders 01 to 03 are ready. Send 04 to 06 only when the
   GRP team says so. **Do not send the HOLD folder** (see "The HOLD folder" below).

## The layer name is the key

Every dataset has one name: `layer` for a point layer or raster, `dataset` for a table. For
example: `early_warning_towers_ddpm`.

- Global Risk counts, cites and removes the data by that name.
- GRP's Word summary recognises GRP's own data by that name.

**Type it exactly as Appendix A gives it.** Never shorten it, and never add `_v2` or a date.

A name must also pass Global Risk's own rule:

- **3 to 40 characters** long;
- only **lower-case letters, digits and underscores**;
- for a raster, starting with `population_`, `hazard_`, `risk_` or `vulnerability_`.

Every name in Appendix A already fits; the longest is 36 characters. The GRP page checks this
rule when you click **Check**. Claude Desktop does not check it: Global Risk declines the name
after you send it.

## Step 1: Put the file on Google Drive and copy its link

1. Upload the dataset's folder from the kit to Google Drive.
2. Right-click the **data file**, not the folder, and choose **Share**. Set **General access** to
   **Anyone with the link** (Viewer).
3. Click **Copy link**. It looks like:

   ```text
   https://drive.google.com/file/d/1AbCdEf...XyZ/view?usp=sharing
   ```

4. Paste it into the `google_drive_link` column of `LINKS.csv` in the kit.

A folder link returns a web page, not your data, so it is refused. Drive shows a virus-scan page
for files over about 100 MB. None of the kit's files are that large; the largest is the villages
file at 27.5 MB.

**The link each route needs:**

- **GRP page:** paste the share link as it is. GRP turns it into the direct-download form.
- **Claude Desktop:** Global Risk needs the direct-download form:

  ```text
  https://drive.google.com/uc?export=download&id=<FILE_ID>
  ```

  `<FILE_ID>` is the long code between `/d/` and `/view`. You can ask Claude to convert it.

## Step 2: Open Share data and choose the kind

**GRP:**

1. Sign in to GRP and click **Share data** in the top bar.
2. Under **What are you sharing?**, choose the kind. The fields below change with it.

| Kind on the page | Use it for | Kit folders |
|---|---|---|
| Point layer | GeoJSON points, counted against the flood layer | 01, 02, 03, HOLD |
| Raster | GeoTIFF: a hazard, risk or vulnerability class grid (0-5), or a population count grid | 04, 06 |
| Table | CSV. It becomes a feed Global Risk can query and cite, never an exposure count | 05 |
| Document | A report or guideline PDF that Global Risk archives and cites | none in the kit |
| Risk weights | Changes how every user's flood risk level is computed | **Do not use** without the data owner's written agreement |

**Claude Desktop:** the kind is the `kind` argument of `contribute_submit`: `vector` (the page's
Point layer), `raster`, `table`, `document` or `weights`.

## Step 3: Fill in the fields

**GRP:** type or paste each value from the dataset's sheet in Appendix A. Each field has a help
line under it. Three things differ from the kit's `manifest.yaml`:

- **Countries** is plain comma-separated text, such as `Thailand`, not `["Thailand"]`.
- **Legend**, **Declared contract** and **Columns** take one line of JSON, such as
  `{"1": "Very low", "2": "Low"}`. The manifest writes them over several lines. Appendix A gives
  the one-line form ready to paste.
- **File link** takes your Drive share link as it is.

**Claude Desktop:** you do not fill in a form. Paste the dataset's `manifest.yaml`, with your
link, into the chat (Step 5).

## Step 4: Check before you send

**GRP:**

1. Click **Check**. **Nothing is sent yet.**
2. One of three things happens:
   - **Red fields.** A red note under a field says what is wrong, such as "Required." or "Write
     the date as YYYY-MM". The banner reads "Fix the marked fields, then check again." Fix
     them and click **Check** again.
   - **A pop-up: "This name is already on Global Risk".** A contribution with this name is
     already there, sent by this Hub, another Hub, or through Claude Desktop. **Nothing was
     sent.** Click **I understand**, then read "To replace or remove a layer" below. **Do not
     change the name** to get past it.
   - **Send this to Global Risk?** The check passed. The notes list what GRP changed, for
     example "The Google Drive link was changed to its direct-download form." Go to Step 5.

**Check** looks only at the fields and the name; it does not download your file. For a point
layer, the file is read when you click **Send** (Step 5). GRP downloads it first and refuses it
if the file is over 50 MB or has a field named like a phone, fax, e-mail, contact or LINE ID. In
that case the row reads **Not sent**, says why, and nothing reaches Global Risk.

**Claude Desktop:** there is no Check button, and nothing stops a duplicate name. Before
submitting, ask:

```text
Use contribute_status with no arguments and list my contributions. Is there a row whose layer is early_warning_towers_ddpm?
```

```text
Use platform_capabilities: which layers does Global Risk hold for Thailand, and is early_warning_towers_ddpm one of them?
```

If either finds the name, **stop**. Do not submit, and read "To replace or remove a layer".

## Step 5: Send

**GRP:**

1. Open **Exactly what will be sent** and read it: the JSON is exactly what Global Risk
   receives. Confirm the name, the link and the numbers in the description.
2. Tick **I understand this becomes available to every Global Risk user.**
3. Click **Send to Global Risk**. The button works once.
4. The banner reads: "Sent. Global Risk is downloading and checking the file; this can take a few
   minutes." A send can take up to about four minutes. You can leave the page: the top bar tells
   you when it lands.
5. Write the time in `LINKS.csv`.

**Claude Desktop:** paste this, with the dataset's manifest from the kit and your own link:

```text
Please submit this to the Global Risk Platform with contribute_submit.
Change my Google Drive link to its direct-download form and put it in url.
Keep the layer name exactly as written. Submit it once only; if the call times out, do not
retry, run contribute_status instead.
My link: https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing

<paste manifest.yaml here>
```

Claude makes this call (early-warning towers shown):

```json
{
  "tool": "contribute_submit",
  "kind": "vector",
  "manifest": {
    "layer": "early_warning_towers_ddpm",
    "url": "https://drive.google.com/uc?export=download&id=<FILE_ID>",
    "title": "Early-warning towers and equipment, Thailand (DDPM)",
    "description": "One point per DDPM early-warning resource (1,533), mostly warning towers, with the site name and administrative area.",
    "source": "Thailand DDPM, compiled by ADPC",
    "license": "unstated",
    "vintage": "2026-09",
    "countries": ["Thailand"],
    "name_field": "name",
    "usage_notes": "…"
  }
}
```

## Step 6: Read the result

**GRP:** the result appears in **Contributions**, at the bottom of the page. Click **Reload** if
it has not changed. Each row shows the title, a status, the kind, the name, who sent it, the
**Global Risk ID** (the `contribution_id`) and, once checked, **Global Risk read N features**.

| Status on the page | Global Risk's state | What it means | What you do |
|---|---|---|---|
| Sending / Checking whether it arrived | (not answered yet) | Global Risk is downloading and checking the file | Wait. Do not send again |
| **Live on Global Risk** | `approved` | Every Global Risk user's answers can count it now. Only a Global Risk reviewer can remove it | Write the Global Risk ID in `LINKS.csv`, then Step 8 |
| **Waiting for a Global Risk reviewer** | `staged` or `pending` | Stored for review. Only you and the reviewers see it, marked PREVIEW. Not seen on the current deployment, which auto-approves | Test it (Step 8). Withdraw it yourself if it is wrong (Step 9) |
| **Declined: fix and resend** | `declined` | Nothing landed. There is **no contribution_id**, and `contribute_status` does not list it. The row lists every problem | Step 7 |
| **Rejected by a reviewer** | `rejected` | A reviewer turned it down | Read the decision note, then Step 7 |
| **Withdrawn** | `withdrawn` | Taken back. The name is free again | Send the corrected file once, if needed |
| **Not sent** | (varies) | GRP could not send it, or could not confirm it arrived. The row says why | See "If something goes wrong" |

> **Note:** on the current deployment, a clean submission comes back **Live on Global Risk**
> (`approved`), cited as "auto-approved, no human reviewed this layer". This was confirmed on
> 30 September 2026. If you ever see **Waiting for a Global Risk reviewer** instead, auto-approve
> has been switched off: tell the GRP team.

**Claude Desktop:** the reply to `contribute_submit` gives the `contribution_id` and the status.
To look again later:

```text
Use contribute_status with contribution_id <your id> and tell me its state.
```

To check every approved contribution and whether it is actually being served:

```text
Use contribute_status with action audit. Is early_warning_towers_ddpm approved and being served?
```

## Step 7: Fix a declined or failed contribution

**GRP:**

1. On the row, click **Fix and send again**. The form fills with what you sent and marks the
   fields Global Risk complained about.
2. Fix them, then **Check** and **Send** again under **the same name**. A declined contribution
   never landed, so this is not a duplicate.

**Claude Desktop:** a declined reply looks like this:

```text
Status: declined
contribution_id: none — nothing was created
layer must be snake_case: lowercase letters, digits, underscores, 3-40 chars
```

1. **Nothing was created.** A declined submission leaves no record: there is no
   `contribution_id`, and `contribute_status` still lists only your earlier contributions. It is
   safe to send again.
2. **Global Risk lists every problem at once.** Fix all of them before you send again.
3. **Global Risk checks the fields before it downloads the file.** So after a decline for
   fields, your Drive link is still untested. If the link is wrong, the next send can be
   declined for that.
4. **Claude will not rename a layer on its own.** It asks you to choose. Give it the name
   exactly:

   ```text
   Use the layer name early_warning_towers_test_kj and resend the same manifest, unchanged apart from the name. Submit it once only.
   ```

   For a real dataset, the name is fixed by Appendix A: never pick a new one. Every real name
   already fits the rule. If a real name is declined, tell the GRP team.

Only after a **declined** reply do you submit the same dataset again straight away.

## Step 8: See it in an answer

**GRP:**

1. On a **Live** row, click **Try it in Planning**. Planning opens with a question written into
   the message box but not sent.
2. The question names Bang Sue District. **Change the district** to Samko, Ang Thong or Tha Pla,
   Uttaradit, so the numbers can be compared with GRP's in the dataset's `TEST.md`.
3. Select the same district on the map, run the flood assessment, and send the question.
4. For a precise question, open **Global Risk layers** above the message box. Tick your layer by
   its exact name and click **Write the question**.
5. Click **Download summary**. Section **5. Global Risk evidence** should have a row for your
   layer, with the layer name in brackets.

If the evidence card says "reused, no new Global Risk lookup", click **Gather again from Global
Risk**. A **staged** layer is visible only to the SERVIR account that sent it. Gather with that
same account, or it will not appear.

**Claude Desktop:** ask the question in the dataset's `TEST.md`, naming the layer. For example:

```text
Using the layer early_warning_towers_ddpm, how many early-warning towers in Tha Pla District, Uttaradit sit in the 100-year flood hazard, by severity? Name the layer you counted and the area of the district polygon you used.
```

A risk question may end with a public receipt, a link anyone can use to replay the answer, so do
not put personal details in a question. Global Risk and GRP often give different numbers, for
reasons that are not mistakes. See "When the numbers differ from GRP" in the companion guide,
`global-risk-contribute-guide.docx`.

## Step 9: Withdraw a contribution

**The GRP page has no withdraw button.** Do it from Claude Desktop, signed in to SERVIR with the
**same account** that sent it:

```text
Use contribute_status with action withdraw and contribution_id <the Global Risk ID>.
```

- **Waiting for a reviewer** (`staged`): the sender can always withdraw it.
- **Live** (`approved`), which is every contribution on the current deployment: Global Risk
  describes `withdraw` as for pending contributions, so **it may be refused**. Try it once.
  - If the reply says **withdrawn**, it worked.
  - If it is refused, ask the GRP team to have a Global Risk reviewer withdraw it with
    `contribute_review`. Give the layer name and the Global Risk ID.

Afterwards:

1. Check it: `Use contribute_status with contribution_id <the Global Risk ID>.` It should read
   `withdrawn`.
2. If it was sent from the GRP page, click **Check on Global Risk** on its row. When it reads
   **Withdrawn**, the name is free, and you may send the corrected file once, under the same
   name.

Answers made while the layer was live still name it when they are replayed. Withdrawing changes
future answers only.

## To replace or remove a layer

**A layer that is Live** (approved): only a Global Risk reviewer can remove it.

1. Give the GRP team both keys: "layer `villages_th_register`, contribution `<Global Risk ID>`".
2. They ask a Global Risk reviewer to withdraw it with `contribute_review`.
3. On the GRP page, click **Check on Global Risk** on the row.
4. When the row reads **Withdrawn** or **Rejected**, the name is free. Send the corrected file
   once, under the same name.

**A layer sent from Claude Desktop** that GRP has counted in a Planning lookup is also refused by
the page. After Global Risk removes it, gather Global Risk evidence again in Planning for a
district where it was counted, so GRP sees it is gone. Then send the corrected file once.

**Never send a corrected file under a new name.** Global Risk would keep both and count both.

## The HOLD folder

`HOLD_evacuation_centres_until_test_layer_withdrawn` contains the same 10,303 evacuation centres
as an older test layer, `evacuation_centres_th_test` (contribution `c66ade79bc2605ac`). **The GRP
page will not stop you**: the names differ, so its name guard lets it through. Sending it now
would make every Global Risk answer count every centre twice. Wait until the GRP team confirms
that the old layer is withdrawn.

## If something goes wrong

| What you see | Why | What to do |
|---|---|---|
| Pill says **Sign in with SERVIR to send**, or "Sign in with SERVIR again…" | GRP's SERVIR sign-in expired, or the stack was rebuilt | Click it, sign in, and send again. Nothing was sent |
| "That is a Google Drive folder…" | You pasted a folder link | Copy the file's link (Step 1) |
| "GRP could not find the file ID…" | The link is not a Drive file link | Copy the link again from **Share → Copy link** |
| "Use an https link that anyone can open…" | The link starts with `http:` | Use the Drive link |
| The link could not be reached, or GRP cannot check that host | The file is not shared, or is on a host GRP cannot read | Share it with "Anyone with the link". Point files must be on Google Drive or GitHub |
| **Not sent**, "The point file is larger than 50 MB." | Too big for GRP to read | Ask the GRP team to split or thin it |
| **Not sent**, the file check named contact fields | The file has a phone, fax, e-mail, contact or LINE ID field | Use the kit's file, which has none. Never remove the check. Then **Fix and send again** |
| **Not sent**, "GRP could not download the file to check it. Nothing was sent." | The file is not shared publicly, or Drive returned a web page | Fix the sharing (Step 1), then **Fix and send again** |
| "At most 500 characters." | Usage notes too long | Shorten them. Do not cut a sentence off |
| "Start with hazard_, risk_, vulnerability_ or population_." | A raster name without the required prefix | Use the name in Appendix A |
| "Global Risk accepts 3 to 40 characters; this name has N." (GRP page) or "layer must be snake_case: lowercase letters, digits, underscores, 3-40 chars" (Claude) | The name is too long or too short, or has capitals, spaces or dashes | Real data: use the Appendix A name. Test copy: use the test name from "Try it yourself", with 2 to 6 lower-case initials |
| "Lower-case letters, digits and underscores, starting with a letter." | Capitals, spaces or dashes in the name, often a `YOURINITIALS` left in | Replace `YOURINITIALS` with your initials in lower-case letters |
| "Give this as a mapping…" | Legend, Declared contract or Columns is not valid JSON | Paste the one-line JSON from Appendix A |
| **Not sent**, and Global Risk could not confirm the submission | GRP timed out waiting; Global Risk may still have stored it | **Do not send again.** Click **Check on Global Risk**. It often turns into Live or Waiting |
| **Not sent**, "Global Risk is not available right now" | Global Risk did not answer | Try again later. Click **Check on Global Risk** first |
| Claude says it cannot find `contribute_submit` | The connector is off or signed out | Switch on SERVIR Global Risk and sign in |
| A Claude Desktop submit timed out | The download and check take minutes | **Do not retry.** Run `contribute_status` with no arguments and look for the layer |

## Try it yourself, without sending anything

Global Risk publishes everything it receives at once (see "Sending means publishing"). So
testers **do not send**. You can learn the whole flow in three ways that send nothing:

1. Fill in the Share data page and click **Check** (test step 2).
2. Ask Claude for a **dry run** of the same data (test step 3).
3. Ask questions about the layer the GRP team has already sent, `early_warning_towers_test_kovitad`
   (test step 4).

Only the GRP team sends, and only after deciding to. Everything below is ready to copy and paste.

### Test step 1: Choose your test name

For practice, use a personal test name. Wherever the blocks below say `YOURINITIALS`, replace
it with your initials: **2 to 6 lower-case letters, a-z only**, such as `kj`. It appears
**twice** in each block: in the layer name and in the title.

| Test copy | Your test name (with initials `kj`) | Characters |
|---|---|---|
| A: early-warning towers | `early_warning_towers_test_kj` | 28 (at most 32) |
| B: volunteer centres | `volunteer_centres_test_kj` | 25 (at most 29) |
| C: population grid | `population_register_test_kj` | 27 (at most 31) |

The rules come from Global Risk:

- **At most 40 characters.** A longer name is declined.
- **Only lower-case letters, digits and underscores.** No capitals, spaces or dashes.
- **A raster name must start with** `population_`, `hazard_`, `risk_` or `vulnerability_`.

If you forget to replace `YOURINITIALS`, the capital letters make the name invalid, and GRP
refuses it on **Check**.

### Test step 2: Check it on the GRP page (sends nothing)

1. Open **Share data** and choose the kind shown in the block: **Point layer** or **Raster**.
2. Copy each value from the block's table into its field.
3. Click **Check**. Fix any red field and click **Check** again.
4. Read **Send this to Global Risk?** and **Exactly what will be sent**. This is exactly what
   would be published.
5. **Stop here.** Do not tick the box, and do not click **Send to Global Risk**. Click **Edit**,
   then **Clear**.

### Test step 3: Dry run in Claude (sends nothing)

Copy the block's "dry run" text into Claude Desktop or Cowork, replace `YOURINITIALS` twice, and
send it. Claude checks the fields against Global Risk's rules and shows the call it would make,
without making it.

Every dry-run block starts with **DRY RUN. Do NOT call contribute_submit**. Never remove that
line. If Claude still shows a `contribution_id`, something **was** sent: tell the GRP team at
once, with the ID.

### Test step 4: Use the layer the GRP team sent

`early_warning_towers_test_kovitad` is live on Global Risk: 1,533 early-warning towers across
Thailand. Anyone can ask about it.

**In Claude Desktop or Cowork:**

```text
Using the layer early_warning_towers_test_kovitad, how many early-warning towers in Tha Pla District, Uttaradit sit in the 100-year flood hazard, by severity? Name the layer you counted and the area of the district polygon you used.
```

```text
Using the risk pack, what is exposed in the 100-year flood in Bang Bua Thong District, Nonthaburi: schools, hospitals, roads and early_warning_towers_test_kovitad? Show counts by severity and name every layer you counted.
```

```text
Use platform_capabilities: is early_warning_towers_test_kovitad listed for Thailand, and as contributed?
```

GRP counts **11** towers in Tha Pla, and **0** in the flood area. Global Risk may count
differently because its Tha Pla polygon is larger: 1,784 km², against GRP's 1,154 km².

**In GRP:**

1. Check that GRP shows you are signed in to SERVIR.
2. In **Planning**, select **Tha Pla**, run the flood assessment, and click **Add Global Risk
   context**. If the card says "reused", click **Gather again from Global Risk**.
3. Once that lookup counts the layer, open **Global Risk layers** above the message box. Tick
   `early_warning_towers_test_kovitad`, click **Write the question**, and send it.
4. Click **Download summary** and open section **5. Global Risk evidence**. The layer appears as
   one Global Risk adds, not as GRP data, because its test name is not a GRP layer name.

A risk answer may end with a **public receipt**, a link anyone can use to replay it. Do not put
personal details in a question.

### If you sent something by mistake

Tell the GRP team at once, with the layer name and the Global Risk ID. Then try to withdraw it
yourself (Step 9).

### Test copy A: early-warning towers (Point layer)

Google Drive link (for the GRP page):

```text
https://drive.google.com/file/d/1elfSyuwuntC_aBY8YRA2mU3WvpTrRHvs/view?usp=sharing
```

GRP Share data page, kind **Point layer**:

| Field | Value |
|---|---|
| Layer name | `early_warning_towers_test_YOURINITIALS` |
| File link | `https://drive.google.com/file/d/1elfSyuwuntC_aBY8YRA2mU3WvpTrRHvs/view?usp=sharing` |
| Title | `TEST copy (YOURINITIALS): Early-warning towers and equipment, Thailand (DDPM)` |
| Description | `One point per DDPM early-warning resource (1,533), mostly warning towers, with the site name and administrative area.` |
| Source | `Thailand DDPM, compiled by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Countries | `Thailand` |
| Name field | `name` |
| Usage notes | `TEST copy sent to try the contribution flow. It duplicates early_warning_towers_ddpm and will be withdrawn. Do not use it for decisions.` |

Claude Desktop or Cowork, dry run (copy all of it):

```text
DRY RUN. Do NOT call contribute_submit and do not send anything.
Check this manifest against Global Risk's contribution rules, list every problem,
and show me the exact contribute_submit call you would make.

kind: vector
layer: early_warning_towers_test_YOURINITIALS
url: https://drive.google.com/uc?export=download&id=1elfSyuwuntC_aBY8YRA2mU3WvpTrRHvs
title: "TEST copy (YOURINITIALS): Early-warning towers and equipment, Thailand (DDPM)"
description: One point per DDPM early-warning resource (1,533), mostly warning towers, with the site name and administrative area.
source: Thailand DDPM, compiled by ADPC
license: unstated
vintage: "2026-09"
countries: [Thailand]
name_field: name
usage_notes: TEST copy sent to try the contribution flow. It duplicates early_warning_towers_ddpm and will be withdrawn. Do not use it for decisions.
```

The GRP team's copy of this dataset is live as `early_warning_towers_test_kovitad`. Ask about it:

```text
Using the layer early_warning_towers_test_kovitad, how many early-warning towers in Tha Pla District, Uttaradit sit in the 100-year flood hazard, by severity? Name the layer you counted and the area of the district polygon you used.
```

GRP's numbers: Tha Pla has **11** towers inside the district, and **0** in the flood area.

### Test copy B: civil-defence volunteer centres (Point layer)

Google Drive link (for the GRP page):

```text
https://drive.google.com/file/d/1ClKdk6G2I-rlZkCaIl4djtA-j-sAIh2K/view?usp=sharing
```

GRP Share data page, kind **Point layer**:

| Field | Value |
|---|---|
| Layer name | `volunteer_centres_test_YOURINITIALS` |
| File link | `https://drive.google.com/file/d/1ClKdk6G2I-rlZkCaIl4djtA-j-sAIh2K/view?usp=sharing` |
| Title | `TEST copy (YOURINITIALS): Civil-defence volunteer (OPPR) centres, Thailand (DDPM)` |
| Description | `One point per civil-defence volunteer centre (8,199) with its type and administrative area. Telephone, fax, e-mail and street address are excluded.` |
| Source | `Thailand DDPM, compiled by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Countries | `Thailand` |
| Name field | `name` |
| Usage notes | `TEST copy sent to try the contribution flow. It duplicates civil_defence_volunteer_centres_ddpm and will be withdrawn. Do not use it for decisions.` |

Claude Desktop or Cowork, dry run (copy all of it):

```text
DRY RUN. Do NOT call contribute_submit and do not send anything.
Check this manifest against Global Risk's contribution rules, list every problem,
and show me the exact contribute_submit call you would make.

kind: vector
layer: volunteer_centres_test_YOURINITIALS
url: https://drive.google.com/uc?export=download&id=1ClKdk6G2I-rlZkCaIl4djtA-j-sAIh2K
title: "TEST copy (YOURINITIALS): Civil-defence volunteer (OPPR) centres, Thailand (DDPM)"
description: One point per civil-defence volunteer centre (8,199) with its type and administrative area. Telephone, fax, e-mail and street address are excluded.
source: Thailand DDPM, compiled by ADPC
license: unstated
vintage: "2026-09"
countries: [Thailand]
name_field: name
usage_notes: TEST copy sent to try the contribution flow. It duplicates civil_defence_volunteer_centres_ddpm and will be withdrawn. Do not use it for decisions.
```

Once the GRP team has sent the real layer, ask:

```text
Using the layer civil_defence_volunteer_centres_ddpm, how many civil-defence volunteer centres in Samko District, Ang Thong would be in the 100-year flood hazard, by severity? Name the layer you counted and the area of the district polygon you used.
```

GRP's numbers: Samko has **4** centres, and all **4** are in the flood area. For Bang Bua Thong,
Nonthaburi, it is **8** of **8**.

### Test copy C: population grid (Raster, experimental)

Google Drive link (for the GRP page):

```text
https://drive.google.com/file/d/1uWr4-4km0a0pqWA5gTsNuJOWYiEQx9PP/view?usp=sharing
```

GRP Share data page, kind **Raster**:

| Field | Value |
|---|---|
| Layer name | `population_register_test_YOURINITIALS` |
| File link | `https://drive.google.com/file/d/1uWr4-4km0a0pqWA5gTsNuJOWYiEQx9PP/view?usp=sharing` |
| Title | `TEST copy (YOURINITIALS): Registered population count, Thailand (village register, ~1 km, EXPERIMENTAL)` |
| Description | `Registered residents summed into ~1 km pixels at each village point (56,574,492 people). A count grid, not classes.` |
| Source | `Thailand village register, delivered to ADPC; gridded by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Legend | leave empty |
| Declared contract | `{"dtype": "float32", "valid_min": 0, "valid_max": 991499.0}` |
| Usage notes | `TEST copy sent to try the contribution flow. It duplicates population_th_village_register and will be withdrawn. Do not use it for decisions.` |

Claude Desktop or Cowork, dry run (copy all of it):

```text
DRY RUN. Do NOT call contribute_submit and do not send anything.
Check this manifest against Global Risk's contribution rules, list every problem,
and show me the exact contribute_submit call you would make.

kind: raster
layer: population_register_test_YOURINITIALS
url: https://drive.google.com/uc?export=download&id=1uWr4-4km0a0pqWA5gTsNuJOWYiEQx9PP
title: "TEST copy (YOURINITIALS): Registered population count, Thailand (village register, ~1 km, EXPERIMENTAL)"
description: Registered residents summed into ~1 km pixels at each village point (56,574,492 people). A count grid, not classes.
source: Thailand village register, delivered to ADPC; gridded by ADPC
license: unstated
vintage: "2026-09"
declared: {"dtype": "float32", "valid_min": 0, "valid_max": 991499.0}
usage_notes: TEST copy sent to try the contribution flow. It duplicates population_th_village_register and will be withdrawn. Do not use it for decisions.
```

Once the GRP team has sent the real layer, ask:

```text
Using the layer population_th_village_register, how many people in Samko District, Ang Thong live in the 100-year flood zone, by severity? Name the population layer you used and the area of the district polygon.
```

GRP's numbers: Samko has **16,571** registered people, and **12,633** of them are in the flood
area. For Tha Pla, it is **3,927** of **38,316**.

## Appendix A: what to type for each kit dataset

These are the **real** layer names. Only the one named person who sends each real dataset uses
them. Testers use "Try it yourself" above.

Copy each value exactly. Leave a field empty only where the table says so. Where the page shows
a drop-down (Validation, Cadence, Pack), choose the value shown.

### 01 Early-warning towers: Point layer

| Field | Value |
|---|---|
| Layer name | `early_warning_towers_ddpm` |
| File link | your Drive link to `early_warning_towers_ddpm.geojson` |
| Title | `Early-warning towers and equipment, Thailand (DDPM)` |
| Description | `One point per DDPM early-warning resource (1,533), mostly warning towers, with the site name and administrative area.` |
| Source | `Thailand DDPM, compiled by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Countries | `Thailand` |
| Name field | `name` |
| Usage notes | `Counts tell you how many warning points sit in the flood hazard layer, i.e. which may be damaged or unreachable in a 100-year flood. Licence and vintage are not confirmed by the data owner; 'unstated' and the delivery month are used until they are.` |

Expect **1,533** features.

### 02 Civil-defence volunteer centres: Point layer

| Field | Value |
|---|---|
| Layer name | `civil_defence_volunteer_centres_ddpm` |
| File link | your Drive link to `civil_defence_volunteer_centres_ddpm.geojson` |
| Title | `Civil-defence volunteer (OPPR) centres, Thailand (DDPM)` |
| Description | `One point per civil-defence volunteer centre (8,199) with its type and administrative area. Telephone, fax, e-mail and street address are excluded.` |
| Source | `Thailand DDPM, compiled by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Countries | `Thailand` |
| Name field | `name` |
| Usage notes | `Response capacity, not shelter: a centre in the hazard layer may itself be cut off. Licence and vintage are not confirmed by the data owner; 'unstated' and the delivery month are used until they are.` |

Expect **8,199** features.

### 03 Villages: Point layer

| Field | Value |
|---|---|
| Layer name | `villages_th_register` |
| File link | your Drive link to `villages_th_register.geojson` (27.5 MB) |
| Title | `Villages with registered population, Thailand` |
| Description | `One point per village (80,317) with registered male, female and total population and households (56,605,825 people in all).` |
| Source | `Thailand village register, delivered to ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Countries | `Thailand` |
| Name field | `name` |
| Usage notes | `650 villages whose male + female does not equal the total, or whose total is implausible, carry no population (GRP's rule). 80 villages with projected coordinates are left out. Global Risk counts villages, not people; see population_th_village_register for a headcount. Population is where people are registered, not where they are. Licence and vintage are not confirmed by the data owner; 'unstated' and the delivery month are used until they are.` |

Expect **80,317** features.

### 04 Population grid (optional, experimental): Raster

Send only when the GRP team says so.

| Field | Value |
|---|---|
| Layer name | `population_th_village_register` |
| File link | your Drive link to `population_th_village_register.tif` |
| Title | `Registered population count, Thailand (village register, ~1 km, EXPERIMENTAL)` |
| Description | `Registered residents summed into ~1 km pixels at each village point (56,574,492 people). A count grid, not classes.` |
| Source | `Thailand village register, delivered to ADPC; gridded by ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Legend | leave empty (a `population_` grid has no legend) |
| Declared contract | `{"dtype": "float32", "valid_min": 0, "valid_max": 991499.0}` |
| Usage notes | `EXPERIMENTAL: each village's whole population sits in the pixel of its point, so a flood edge through a village counts all or none of it. Same register GRP reports; WorldPop would be the independent alternative.` |

### 05 Sub-district population table (optional): Table

Send only when the GRP team says so. The CSV is 492 KB, over the page's 200 KB paste limit.
**Leave CSV empty and use CSV link.**

| Field | Value |
|---|---|
| Dataset name | `th_subdistrict_population` |
| Title | `Registered population by sub-district, Thailand` |
| Description | `Registered population, male, female and households for 7,436 sub-districts, with English names and codes.` |
| Source | `Thailand sub-district boundary delivery (DOPA register)` |
| Validation | `official-statistic` |
| Licence | `unstated` |
| Vintage | `2020-01` |
| Cadence | `annual` |
| Columns | `{"subdistrict_code": "Subdistrict_code", "subdistrict": "Subdistrict", "district": "District", "province": "Province", "population": "Population", "male": "Male", "female": "Female", "households": "Households", "pop_year": "Pop_year"}` |
| Units | `people (households for households); pop_year is the register year` |
| CSV | leave empty |
| CSV link | your Drive link to `th_subdistrict_population.csv` |
| Pack | `risk` |
| Date field | leave empty |
| Usage notes | `A lookup table: it reaches answers through feeds_query only and never enters Global Risk's exposure counts. Licence and vintage are not confirmed by the data owner; 'unstated' and the delivery month are used until they are.` |

A table never enters Global Risk's exposure counts. Test it with a `feeds_query` question, not a
flood-exposure question.

### 06 GRP's flood tiles (optional): Raster

Send only when the GRP team says so. It probably duplicates Global Risk's own flood layer, and is
useful only to test whether both engines agree on the same input.

| Field | Value |
|---|---|
| Layer name | `hazard_flood_thailand_rp100` |
| File link | your Drive link to `hazard_flood_thailand_rp100.tif` |
| Title | `Flood depth, 1-in-100 year, Thailand (JRC tiles, reclassed 1-5)` |
| Description | `The 100-year flood-depth tiles GRP assesses with, clipped to Thailand and reclassed to five depth bands matching Global Risk's live flood legend. 0 means dry or no data: the source does not tell them apart.` |
| Source | `JRC Global Flood Hazard Maps (RP100 depth tiles), as delivered to ADPC` |
| Licence | `unstated` |
| Vintage | `2026-09` |
| Legend | `{"1": "Very low (<= 0.5 m)", "2": "Low (0.5-1 m)", "3": "Moderate (1-1.5 m)", "4": "High (1.5-2 m)", "5": "Very high (> 2 m)"}` |
| Declared contract | `{"dtype": "uint8", "valid_min": 0, "valid_max": 5, "nodata": 0}` |
| Usage notes | `Likely the same model as Global Risk's hazard_flood (derived from JRC GLOFAS v2.1): use it to test that both engines agree on identical input, not as new evidence. No risk recipe exists for flood_thailand until a weights contribution adds one.` |

GRP's Planning page always asks about Global Risk's standard flood layer, so this layer appears
in Claude's answers but not in GRP's Word summary.

### HOLD Evacuation centres: do not send yet

Layer name `evacuation_centres_ddpm`. See "The HOLD folder" above. When the GRP team releases it,
fill it in from its `manifest.yaml` the same way as 01.

## Appendix B: Claude Desktop equivalents at a glance

| On the GRP page | Ask Claude Desktop |
|---|---|
| **Check** (field check) | No equivalent. Global Risk checks on submit |
| **Check** (name guard) | `Use contribute_status with no arguments. Is <name> there?` and `Use platform_capabilities: does Global Risk hold <name> for Thailand?` |
| **Send to Global Risk** | `Submit this with contribute_submit, kind <vector/raster/table>, using this manifest …` |
| **Reload**, **Check on Global Risk** | `Use contribute_status with contribution_id <id>.` |
| The **Contributions** list | `Use contribute_status and show me my contributions and their state.` |
| **Fix and send again** | Fix the manifest, then submit again under the same name (only after `declined`) |
| No withdraw button | `Use contribute_status with action withdraw and contribution_id <id>.` |
| **Try it in Planning** | The question in the folder's `TEST.md`, naming the layer |
| Nothing on the page | `Use contribute_status with action audit.` Lists every approved contribution and whether it is served |

For the full Claude Desktop walk-through, results sheet and "When the numbers differ from GRP",
see the companion guide, `global-risk-contribute-guide.docx`, in the same folder.
