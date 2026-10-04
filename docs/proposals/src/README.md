# Proposal sources

`GRP_Live_Flood_Intelligence_Proposal_2026-10-04.docx` is generated from these files.

```bash
dot -Tpng -Gdpi=170 arch.dot -o arch.png
dot -Tpng -Gdpi=170 horizons.dot -o horizons.png
npm install docx
node make_proposal.js proposal.docx
```

Open the result in Word and update the table of contents (right-click, Update Field) before
sharing.
