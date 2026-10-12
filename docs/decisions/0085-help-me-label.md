# 0085 — "Help me label": questions from analysis, answers as context and person links

- Status: accepted (M4 step 13)
- Deciders: agent (autonomous; no human gate)

## Context

PRODUCT.md §3: "after L2, the app may ask up to 5 targeted, skippable questions, for example 'Where was Day 3?' or 'Is this the same person in these clips?'". M4 acceptance 7: "Help me label (S24) creates only `person_link` and context records. A test asserts that no face or biometric data is stored." Face recognition and named-people identification must not be built (CLAUDE.md). Titles may name people only from the trip context or the owner's input (invariant 16).

## Decision

- **Questions come from what analysis already knows**, with no AI call and nothing about faces (`library/labeling.py`):
  - **place** (at most 2): a day with footage whose date has no place in the itinerary - "Where were you on Day 1 (Friday 12 June)?" - with up to four of its clips;
  - **same_person** (at most 2): two or three clips of one day that the vision observations say show one or a few people (`people: one | few`, a count, not an identity), each within half an hour of the last - "Is this the same person in these clips?";
  - **event** (at most 1): the day with the most high-interest moments whose itinerary day has no notes.
  - Up to five are open at a time, place first; S24's "Question n of 5" counts the batch it shows, and a later batch may come once those are answered (never the same question).
  - Capture times are compared as local wall-clock times: phone clips carry an offset, camera-local times none, and a clip without a time has no day.
  - A question the trip context has since answered (a day's place or notes filled in S7) is closed, never asked.
  - S24 is offered after L2 (its entry point, step 14g); place questions need no vision, the others use L2's observations. Each is stored with its **subject** (the date, or the clips), so an answered or skipped question is never asked again; a later one may be (another day, once this one is known). Each shows one kept sample frame per clip.
- **Answers are records the owner made**, nothing else:
  - place: the day's place in the trip context (the day is added to the itinerary when missing);
  - event: appended to the day's notes in the trip context;
  - same person: Yes needs a name (else 422); it links each clip to that label in `person_link` (a label, a clip, the question, a time); a name matching a trip-context person (ignoring case) uses that person's label, a new one is added to the trip context's people; No and Not sure link nothing;
  - skip: the question is closed with no record.
  Trip-context changes are validated as a whole before they are saved (an answer that would make the context invalid, such as a 51st person, is refused), and are saved as the owner's (`source: user`), so summaries and edits that use the context see them (PRODUCT.md §3).
- **No biometric data**: `person_link` holds `id, label, asset_id, question_id, created_at`; the test answers every question and asserts that no table or column of the project names faces, landmarks, identities or biometrics.
- API: `GET /projects/{pid}/labeling-questions`, `POST …/{qid}/answer` (`docs/ui/API_MAP.md`).

## Consequences

- An owner who names people gives the editor names it may use in titles and captions (invariant 16), linked to the clips they confirmed.
- Showing a clip's linked people in S11 and using the links in retrieval are later steps.
