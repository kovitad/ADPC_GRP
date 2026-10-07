# Planner map: one side panel instead of floating cards

Status: decided and built on 4 October 2026 (ADR-0060), with the recommended answer to every
question.

## The problem (owner, 4 October 2026)

"We got cards floating and covering each other now. We need a better UX, since we have a lot of
things popping up and covering each other, and they can't be unfolded easily."

What the Planner map shows today, with the Live layer on and a district selected:

| Thing | Where it appears | Problem |
| --- | --- | --- |
| Camera, report, facility and road cards | Floating popup on the point | Covers the point and its neighbours. Several cameras share a spot, so you cannot choose which one opens. |
| District profile | Floating popup on the district | A second kind of popup, opened by a click anywhere inside the district |
| Layers panel | Fixed box on the right, 310 px wide, one long list | Covers a third of the map. Nothing folds; the legends are always open. |
| Data & run | A second box in the same place | Competes with Layers |
| "District selected" message | A chip under the search box | Stays on screen and covers the map's top left |
| Name tooltips | Follow the mouse over districts | Pile on top of everything else |

## Design: one dock, one thing at a time

```text
┌──────────────────────── map ────────────────────────┬─ dock (360 px) ───────────┐
│ [Search…]                                           │ [Layers] [Details] [Run]  │
│                                                     │───────────────────────────│
│        ●  ◉ ← the selected point keeps a ring       │ ◀ Back to 3 here          │
│                                                     │ Camera · BMA Traffic      │
│                                                     │ Central barrier near the  │
│                                                     │ police box, Vibhavadi Rd  │
│                                                     │ [ live picture        ]   │
│                                                     │ Updates every 10 s [Pause]│
│                                                     │ Flooding reported 120 m   │
│                                                     │ ▸ What this is not        │
│                                                     │ Source · time             │
│   (toast) Chatuchak selected · Check Global Risk ✕  │                       [»] │
└─────────────────────────────────────────────────────┴───────────────────────────┘
```

1. **One dock on the right, with tabs:** Layers, Details and Run.
   - Only the dock covers the map. Nothing else floats except a hover name.
   - `»` folds the dock to a thin rail of three icons, so the whole map shows. The browser
     remembers the choice.
   - Phones keep today's bottom sheet, with the same three tabs.
2. **Clicking a point opens Details**, not a popup:
   - the dock switches to the Details tab;
   - the point gets a ring, and the map moves only if the point would sit under the dock;
   - Esc, the `✕` or a click on empty map closes Details and removes the ring;
   - clicking another point replaces the card. Cards never stack.
3. **Points on top of each other:** when a click touches more than one point (within about
   12 px), Details first shows a short list ("3 here: 2 cameras, 1 report"), each row with its
   icon. Choosing a row opens its card, and "Back to 3 here" returns to the list.
4. **The district profile moves into Details too.** Clicking empty space inside a district
   selects it and shows its profile card in the dock. Clicking the already selected district
   does nothing new.
5. **Layers tab folds into sections**, and each section remembers whether it is open:
   - Base map and boundaries (open by default);
   - Assessment (flood depth, scenario and centres);
   - Live layer (Bangkok, Nonthaburi);
   - Global Risk and vulnerability.

   Each switch shows its legend only while it is on, and the long legends fold under
   "Legend ▸". The "Live now" list moves to the Details tab, opened from a "Live now (22)"
   button in the Live section.
6. **Messages become a toast:** "Chatuchak selected · Check Global Risk", at the bottom centre
   of the map. It hides after 8 seconds, and the same actions stay in the chat.
7. **Hover shows a name only**, for points and districts, and never on a phone.

### Unchanged

- the card content and wording, the live picture relay and the five-minute refresh;
- the rules: not a flood map, not a warning, "flooding reported nearby", no officer checks,
  credits shown;
- the summary download's map picture, which does not use the live map.

## Steps

1. Dock with tabs and the fold rail; move Layers and Run into it. No change to their contents yet.
2. Details tab. All cards render there instead of popups; ring the selected point; Esc and an
   empty click close it.
3. Pick list for overlapping points, found from the loaded layers by screen distance.
4. Layers sections and folding legends; "Live now" moves to Details.
5. Toast for place messages; hover names only.
6. Check in the headless harness at 1400, 1024 and 390 px wide, then by a signed-in planner.

## Questions for the owner

1. **Dock side:** right (recommended, where Layers is today) or left, beside the chat?
2. **Pick list for points on top of each other:** yes (recommended), or always open the top one?
3. **District click:** show the profile in the dock (recommended), or keep today's popup for
   districts only?
