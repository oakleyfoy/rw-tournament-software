export const TIME_WINDOWS_HELP = {
  title: "Time Windows (Advanced Mode Capacity + Scheduling)",
  summary: [
    "Use Time Windows when court availability is not the same all day or not the same every day.",
    "Time Windows tell the system exactly when matches can be played.",
    "This is the source used to generate the schedule grid (day × time × courts)."
  ],

  whatItControls: [
    "Capacity based on the exact playable windows you define (not a simple daily hours estimate).",
    "Slot generation for the schedule page (the grid of courts and times).",
    "Prevents matches from being placed during unavailable times (late starts, early closes, breaks)."
  ],

  whatItDoesNotControl: [
    "Which specific matches go where (that happens in the schedule page / auto-scheduler).",
    "Team rest rules and conflicts (not in Phase 3A/3B V1).",
    "Bracket advancement logic (later phase)."
  ],

  whenToUse: [
    "Friday starts late (check-in, travel day, opening reception).",
    "Different days have different hours (e.g., Sat full day, Sun half day).",
    "You need built-in breaks (lunch, ceremonies, photo time).",
    "Some courts are only available part of the day.",
    "You want accurate start times and a realistic scheduling grid."
  ],

  whenNotToUse: [
    "All days are basically the same hours with no breaks.",
    "You only need a quick capacity estimate (use Days & Courts)."
  ],

  coreConcepts: [
    "A Time Window is a playable block of time on a specific day.",
    "Each window produces schedule slots on each court, based on match length and slot rules.",
    "If a time is not inside a window, the system treats it as unavailable."
  ],

  howToEnter: [
    "Pick the day (Friday / Saturday / Sunday).",
    "Enter a Start Time and End Time for a playable block.",
    "Add another window if you need a gap (example: 9:00–12:00 and 1:00–6:00).",
    "Repeat for each day that has different hours."
  ],

  examples: [
    {
      label: "Example A — Late start Friday + lunch break Saturday + short Sunday",
      lines: [
        "Friday: 1:00 PM–6:00 PM (travel/check-in day)",
        "Saturday: 9:00 AM–12:00 PM and 1:00 PM–6:00 PM (lunch break)",
        "Sunday: 9:00 AM–1:00 PM (half day)"
      ]
    },
    {
      label: "Example B — Courts not all available all day",
      lines: [
        "Courts 1–3 available 9:00 AM–6:00 PM",
        "Courts 4–6 available 12:00 PM–6:00 PM",
        "If your UI supports court-specific windows later, this is how you model it.",
        "For now, define windows for the tournament and manage court differences manually."
      ]
    }
  ],

  importantRules: [
    "Time Windows are only used when Advanced mode is selected.",
    "If Simple mode is selected, Time Windows are ignored (and should appear disabled).",
    "Windows should never overlap on the same day (avoid duplicate capacity).",
    "If you need a break, create two windows with a gap instead of one long window."
  ],

  commonMistakes: [
    "Forgetting Sunday is a half day (leads to over-scheduling).",
    "Using one long window when you really need a lunch break (matches get placed during lunch).",
    "Overlapping windows (double-counts capacity and creates duplicate slots).",
    "Entering end time earlier than start time (invalid window)."
  ],

  oneSentence: [
    "Time Windows = the exact times matches are allowed to be scheduled."
  ]
};

