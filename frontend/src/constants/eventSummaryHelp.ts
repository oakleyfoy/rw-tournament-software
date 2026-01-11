export const EVENT_SUMMARY_HELP = {
  title: "Event Summary — How this event is configured",

  sections: [
    {
      heading: "Event Type: Mixed (8 teams)",
      bullets: [
        "This is a Mixed event (typically male/female teams).",
        "This event contains 8 total teams.",
        "The system schedules matches for this event independently from other events."
      ]
    },

    {
      heading: "Status: Not Started",
      bullets: [
        "Not Started means this event has not begun play.",
        "Matches may exist as placeholders, but no results or advancement has occurred.",
        "Status changes later during live tournament control (future phase)."
      ]
    },

    {
      heading: "Guarantee Matches: 5",
      bullets: [
        "Each team is guaranteed at least 5 matches in this event.",
        "The scheduler must create enough matches to satisfy this guarantee.",
        "Guarantee affects capacity calculations but does not assign teams yet."
      ]
    },

    {
      heading: "Template Type: Round Robin Only",
      bullets: [
        "Round Robin means teams play multiple opponents in a pool format.",
        "There is no bracket or elimination phase in this template.",
        "All matches are considered standard matches."
      ]
    },

    {
      heading: "Standard Match Length: 2 hours",
      bullets: [
        "Each match is scheduled as a 2-hour block.",
        "This duration is used for capacity calculations and slot fitting.",
        "Matches cannot be placed into slots shorter than this length."
      ]
    },

    {
      heading: "Capacity Metrics: Standard: 28 × 2:00",
      bullets: [
        "The system generated 28 total matches to satisfy the guarantee.",
        "Each match is 2 hours long.",
        "28 matches × 2 hours = 56 total court-hours required."
      ]
    },

    {
      heading: "Hours Required (Guarantee 5): 56",
      bullets: [
        "This is the total amount of court time this event will consume.",
        "These hours are deducted from tournament capacity once the event is finalized.",
        "If tournament capacity is exceeded, the event cannot be finalized."
      ]
    },

    {
      heading: "Important Notes",
      bullets: [
        "No teams are assigned to matches yet (placeholder scheduling).",
        "Changing guarantee or match length will change hours required.",
        "This event does not schedule itself — scheduling happens later."
      ]
    }
  ],

  oneSentence: "This summary explains how the system calculated the number of matches and total court time for this event."
};

