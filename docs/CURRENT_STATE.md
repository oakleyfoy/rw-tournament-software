# CURRENT_STATE

## Phase
**SMS Foundation / Phase 2.5**
- Core Twilio + manual send infrastructure exists.
- Automation toggles/templates exist, but full auto-trigger wiring is not complete.
- No frontend SMS admin UI yet.

## Implemented (SMS)

### Backend models
- `SmsLog` (`sms_log`) for send history/audit
- `SmsTemplate` (`sms_template`) for customizable message bodies
- `TournamentSmsSettings` (`tournament_sms_settings`) for per-tournament auto toggles
- Team phone fields available (`p1_cell`, `p2_cell`, etc.)

### Service
- `twilio_service.py`
  - E.164 phone normalization/validation
  - Twilio client wrapper
  - Dry-run mode if credentials missing

### API routes
Base: `/api/tournaments/{tournament_id}/sms`

Implemented endpoints:
- `GET /status`
- `POST /blast`
- `POST /team/{team_id}`
- `POST /match/{match_id}`
- `POST /timeslot`
- `POST /preview/blast`
- `GET /log`
- `GET /settings`
- `PATCH /settings`
- `GET /templates`
- `PUT /templates/{message_type}`
- `POST /templates/reset`

### Templates/toggles currently modeled
- `first_match`
- `post_match_next`
- `on_deck`
- `up_next`
- `court_change`

## Gaps Remaining

1. **Targeting gaps**
- No direct endpoint for:
  - event-wide send
  - division-wide send
  - player-specific send

2. **Automation gaps**
- Not fully wired end-to-end:
  - 24h before first match
  - post-match next-match text
  - court/time change text
  - on-deck/up-next auto sends

3. **Identity model gap**
- Player-level model/linking not yet implemented (still team phone field based)

4. **Frontend gap**
- No SMS management tab/page in React app

5. **Compliance/ops gap**
- Opt-in/opt-out lifecycle and STOP/START webhook handling not complete

## Immediate Next Steps

1. Add **Player + TeamPlayer** model for player-level targeting and consent.
2. Add SMS endpoints for **event**, **division**, and **player** scopes.
3. Implement automation service with dedupe keys for:
   - first-match-24h
   - post-match-next
   - court/time change
4. Add frontend SMS admin UI:
   - audience selection
   - template editing
   - preview recipients
   - logs + toggle controls
5. Add Twilio compliance flow:
   - opt-in/out persistence
   - inbound STOP/START/HELP webhook
