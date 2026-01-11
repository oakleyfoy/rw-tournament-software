export const SCHEDULE_PAGE_HELP = {
  title: "Schedule Page — How scheduling works",
  sections: [
    {
      heading: "What this page is",
      bullets: [
        "This page is where matches are placed onto courts and times.",
        "Scheduling always happens using placeholder matches first.",
        "No real teams are assigned yet — that happens later."
      ]
    },
    {
      heading: "Schedule Versions",
      bullets: [
        "A schedule version is a saved snapshot of a schedule.",
        "You always work in a Draft version.",
        "Final schedules are locked and cannot be edited.",
        "If no schedule exists yet, a 'Create Draft' button will appear above.",
        "Click the 'Create Draft' button to begin scheduling."
      ]
    },
    {
      heading: "Create Draft",
      bullets: [
        "This creates an editable schedule workspace.",
        "Nothing is permanent until you finalize it.",
        "You can create multiple drafts later if needed.",
        "You cannot generate slots or place matches without a draft."
      ]
    },
    {
      heading: "Unscheduled Matches panel",
      bullets: [
        "This panel shows matches that exist but are not yet placed on the grid.",
        "Matches appear here only after events are finalized in Setup.",
        "Filters help narrow by: Event, Match type, Duration.",
        "Why it's empty: Either no events are finalized yet, or matches haven't been generated yet."
      ]
    },
    {
      heading: "Schedule Grid",
      bullets: [
        "This grid represents: Days, Times, Courts.",
        "Matches are placed into this grid manually or automatically."
      ]
    },
    {
      heading: "No slots generated",
      bullets: [
        "This message means: The system knows your time windows, but it has not yet converted them into actual schedule slots.",
        "Slots are required before any scheduling can happen."
      ]
    },
    {
      heading: "Required order of operations (very important)",
      bullets: [
        "1. Finalize events in Setup (creates placeholder matches)",
        "2. Create Draft (opens an editable schedule)",
        "3. Generate Slots (builds the grid from time windows)",
        "4. Place matches (manual now, auto later)",
        "5. Finalize schedule (locks it)",
        "If any step is skipped, the page will appear empty."
      ]
    },
    {
      heading: "Common reasons users get stuck",
      bullets: [
        "Forgetting to finalize events",
        "Forgetting to create a draft",
        "Forgetting to generate slots",
        "Expecting teams to appear (they don't yet — by design)"
      ]
    }
  ],
  oneSentence: "This page schedules placeholder matches into time slots. If it's empty, a required setup step hasn't been completed yet."
}
