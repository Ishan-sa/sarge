# Sarge — personal diet enforcer (design)

Approved in chat 2026-09-22.

## Goal
A blunt Telegram bot that logs everything Ishan eats against his trainer's plan
(1800 kcal, 130 g protein), reports what's left, and nags him on a schedule
relative to his actual meals.

## Architecture
- Runs on an always-on Linux box at home as a systemd user service.
- Python 3.12 + python-telegram-bot (polling, JobQueue).
- SQLite database (`~/sarge/data/sarge.db`).
- Brain: Claude Code headless (`claude -p --json-schema`, Sonnet, no tools, no
  settings/MCP) on Ishan's subscription. No API key.

## Division of labour
- **Claude interprets**: turns free text into structured actions (items with
  macros, meal-vs-minor flag, plan slot, edits/deletes, water, steps, vitamin D,
  foods to remember) plus a one-to-two line coaching comment.
- **Python enforces**: stores actions, computes totals and remaining, renders
  the status block, owns every timer. Claude never states totals.

## Data
- `entries` (one per logged message) → `items` (food lines with macros).
- `extras` (water ml, steps, vitamin D) per day.
- `foods` — exact user-supplied label values, preferred over estimates.
- `messages` — last few exchanges for context ("that rice was 200g").
- `state` — owner chat id, reminder bookkeeping.
- A "day" rolls over at 04:00 local (America/Vancouver) so late-night food
  counts toward the day it belongs to.

## Reminders
- Meal due: 3.5 h after the last *meal* (minor items like black coffee don't
  reset it); once per meal; only 08:00–22:00; skipped if protein and all plan
  slots are already done.
- 13:00 nag if nothing logged today.
- 21:00 wrap-up: kcal, protein gap, water, steps, vitamin D, missed slots.

## Commands
`/start` (first user claims the bot; everyone else is ignored), `/today`,
`/week`, `/undo`, `/foods`.

## Error handling
- Claude failure/timeout → reply "Brain timed out, resend", nothing logged.
- Only the owner's chat is served.
- Every Claude action is validated (ids must exist in today's log) before applying.

## Testing
pytest for store totals/day rollover, reminder decisions, and applying brain
results (with a fake brain). Live smoke test on the box.
