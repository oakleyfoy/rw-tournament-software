export const CAPACITY_SOURCE_HELP = {
  title: "Capacity Source (How the system knows how much time you have)",
  bullets: [
    {
      heading: "Option 1 — Use Days & Courts (Simple)",
      lines: [
        "Best for most tournaments.",
        "You are telling the system: \"We have X courts available for Y hours each day.\"",
        "Example: 6 courts × 8 hours/day × 3 days = 144 total court hours.",
        "Use Simple when courts are available all day and you don't need breaks/uneven hours."
      ]
    },
    {
      heading: "Option 2 — Use Time Windows (Advanced)",
      lines: [
        "Use only when exact time availability matters.",
        "You define exact playable time blocks (e.g., Fri 1:00–6:00, Sat 10:30–4:00).",
        "Use Advanced when days differ, courts open late, you need breaks, or exact start times matter."
      ]
    },
    {
      heading: "Important rule",
      lines: [
        "You must choose one: Simple OR Time Windows (never both).",
        "The active mode controls capacity; the other is ignored and should appear disabled."
      ]
    },
    {
      heading: "One-sentence summary",
      lines: [
        "Simple = \"We have these courts for these days.\"",
        "Advanced = \"We can only play at these exact times.\""
      ]
    }
  ]
};

