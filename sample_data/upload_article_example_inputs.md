# Upload + Classify Inputs (Modified Schema)

Use these values in the current `Upload + Classify` form.

## Basic

- `Title`: `City council passes revised climate transit package`
- `Published Date (YYYY-MM-DD)`: `2026-02-24`
- `Category`: `Policy`

## Author

- `Author Name`: `Rohan Iyer`
- `Author Affiliation`: `Urban Affairs Desk`
- `Author Aliases (comma-separated)`: `R. Iyer, Rohan I.`

## Publisher

- `Publisher Name`: `Metro Public Ledger`
- `Publisher Website`: `https://www.metropubledger.example`
- `Publisher Country`: `USA`
- `Publisher Aliases (comma-separated)`: `MPL, Metro Ledger`

## Content

- `Article Content`:
  - Example: `The city council approved a revised transit and emissions package...`

## Classification

- `Label`: `Center`
- `Confidence`: `0.81`
- `Model Version`: `prototype-v1`

## Keywords and Topic Scores

- `Keywords (comma-separated)`: `climate, transit, council, emissions, budget`
- `Topic Scores (topic:score,topic:score)`: `climate:0.89,transport:0.83,economy:0.58,governance:0.76`

## Engagement and Comments

- `Likes`: `212`
- `Shares`: `64`
- `Views`: `4875`
- `Comments (one per line)`:
```text
Nina K|Clear summary of the final vote.|13|2026-02-24T10:11:00Z|insightful
Arun V|Would like cost breakdown details.|4|2026-02-24T10:26:00Z|question
Sam T|Balanced reporting, helpful context.|8|2026-02-24T11:03:00Z
```

## Notes About Modified Fields

- File upload is removed (manual text only).
- `Search Meta` is removed.
- `Publisher metadata` is removed.
- `Author social_profiles` is removed.
- `Keywords` are normalized in backend (trimmed + lowercase) before storage.
