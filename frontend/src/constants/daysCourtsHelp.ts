export const DAYS_COURTS_HELP = {
  title: "Days & Courts (Simple Mode Capacity)",
  summary: [
    "Use this when your courts are generally available the same hours each day.",
    "This setting tells the system how many total court-hours you have for the tournament.",
    "It is used for capacity planning (hours available vs hours required)."
  ],
  whatItControls: [
    "Total tournament court-hours (capacity).",
    "Whether your finalized events fit within that capacity.",
    "The tournament capacity panel (Total / Committed / Remaining)."
  ],
  whatItDoesNotControl: [
    "Exact match start times.",
    "Breaks (lunch, ceremonies, gaps).",
    "Different hours on different days.",
    "Slot generation for the schedule grid (that requires Time Windows)."
  ],
  requiredInputs: [
    "Which days the tournament runs (e.g., Friday–Sunday).",
    "How many courts are available (e.g., 6 courts).",
    "Daily playable hours (start time and end time, or total hours/day)."
  ],
  howTheMathWorks: [
    "Step 1: Compute playable hours per day.",
    "Step 2: Multiply playable hours per day by number of courts.",
    "Step 3: Multiply by number of tournament days.",
    "Result = Total court-hours available (capacity)."
  ],
  examples: [
    {
      label: "Example A (standard full day)",
      lines: [
        "Days: Fri/Sat/Sun (3 days)",
        "Courts: 6",
        "Hours/day: 9:00 AM–5:00 PM = 8 hours",
        "Capacity: 3 days × 6 courts × 8 hours = 144 court-hours"
      ]
    },
    {
      label: "Example B (shorter day)",
      lines: [
        "Days: Sat/Sun (2 days)",
        "Courts: 4",
        "Hours/day: 10:00 AM–3:00 PM = 5 hours",
        "Capacity: 2 × 4 × 5 = 40 court-hours"
      ]
    },
    {
      label: "Example C (fractional match durations still fit in Simple mode)",
      lines: [
        "If matches are 1.5 hours (1:30), you still plan capacity the same way.",
        "Example A has 144 court-hours total.",
        "You could theoretically fit about 144 ÷ 1.5 = 96 match-slots worth of time (before any real-world constraints)."
      ]
    }
  ],
  whenToUse: [
    "All days run about the same time window.",
    "You don't need breaks enforced by the system.",
    "You're planning capacity and building events, not building the exact grid yet."
  ],
  whenNotToUse: [
    "Friday starts late or ends early.",
    "Some courts are only available part of the day.",
    "You need breaks or gaps enforced.",
    "You need exact start times and slot-by-slot scheduling."
  ],
  oneSentence: [
    "Simple mode Days & Courts is for total capacity planning: courts × hours/day × number of days."
  ]
};

