# Manual Schedule Editor - User Guide

## Quick Start

### Accessing the Editor
1. Navigate to your tournament's schedule page: `/tournaments/{id}/schedule`
2. Click the **"✏️ Open Manual Schedule Editor"** button
3. The editor will open with your current draft version selected

### Editor Layout

```
┌──────────────┬─────────────────────────┬──────────────────┐
│ Match Queue  │   Schedule Grid         │   Conflicts      │
│ (Left Panel) │   (Center Panel)        │   (Right Panel)  │
│              │                         │                  │
│ Unassigned   │   Day 1: 2024-01-15    │   Summary        │
│ Matches      │   ┌───┬───┬───┬───┐    │   Unassigned     │
│              │   │   │   │   │   │    │   Violations     │
│ • WF-R1-1    │   ├───┼───┼───┼───┤    │   Slot Pressure  │
│ • WF-R1-2    │   │ M │   │ M │   │    │                  │
│ • MAIN-R2-1  │   └───┴───┴───┴───┘    │   [Refresh]      │
│              │                         │                  │
└──────────────┴─────────────────────────┴──────────────────┘
```

---

## Core Workflows

### 1. Moving an Assigned Match

**Steps**:
1. Find the match in the grid (center panel)
2. Click and drag the match card
3. Drop it on an **empty slot** (green background)
4. The system will:
   - Save the move to the backend
   - Automatically refresh the grid and conflicts
   - Show any new conflicts that arise

**Visual Feedback**:
- **Dragging**: Match card becomes semi-transparent
- **Valid drop target**: Slot highlights with green dashed border
- **Invalid drop target**: Occupied slots don't highlight
- **Saving**: Match card shows "wait" cursor

**Locked Matches**:
- Locked matches have a **🔒 icon** and **purple background**
- You can still move them (admin override)
- They will remain locked after moving

---

### 2. Viewing Unassigned Matches

**Left Panel: Match Queue**
- Shows all matches without assigned slots
- Displays:
  - Match code (e.g., `WF-R1-1`)
  - Stage and round (e.g., `WF R1`)
  - Teams (if assigned)
  - Duration (e.g., `15 min`)

**To assign unassigned matches**:
- Use the **Auto-Fill** or **Grid Population** tools on the main schedule page
- The Manual Editor is for **moving already-assigned matches**, not initial assignment

---

### 3. Checking for Conflicts

**Right Panel: Conflicts & Diagnostics**

**Summary Section**:
- Total slots, matches, assigned, unassigned
- Assignment rate percentage

**Conflict Types**:

1. **⚠️ Unassigned Matches**
   - Matches that don't have a slot yet
   - Shows first 10, with "...and X more" if there are many

2. **🔀 Ordering Violations**
   - Matches scheduled out of logical order
   - Example: Round 2 match scheduled before Round 1
   - Shows which matches and the reason

3. **⏰ Slot Pressure**
   - Slots with unusual assignment counts
   - May indicate double-booking or gaps

**Refresh Button**:
- Manually re-fetch conflicts and grid data
- Useful after making multiple moves

---

### 4. Working with Versions

**Version Selector** (top of page):
- Shows all schedule versions: `v1 (draft)`, `v2 (final)`, etc.
- Select a version to view/edit it

**Draft vs Final**:
- **Draft**: ✏️ Green badge, editing enabled
- **Final**: 📄 Gray badge, read-only

**Editing a Final Version**:
1. Select the final version
2. A banner appears: "Read-only (Final). Clone to Draft to edit."
3. Click **"Clone to Draft"**
4. A new draft version is created and automatically selected
5. You can now edit the new draft

**Undo Model** (Clone-Before-Edit):
- Before making risky changes, clone the current draft
- This creates a "save point" you can return to
- Use the version selector to switch back to previous versions

---

## UI Indicators & States

### Match Card States
| Visual | Meaning |
|--------|---------|
| Blue background | Normal assigned match |
| Purple background + 🔒 | Locked match (won't be moved by auto-assign) |
| Semi-transparent | Currently being dragged |
| Grayed out + wait cursor | Being saved (PATCH in progress) |

### Slot States
| Visual | Meaning |
|--------|---------|
| Green background | Empty slot (valid drop target in draft) |
| White background | Occupied slot (cannot drop here) |
| Green dashed border | Dragging over this slot (valid drop) |
| Gray background | Final version (editing disabled) |

### Loading States
- **"Loading tournament data..."**: Initial page load
- **"Loading matches..."**: Match queue is loading
- **"Loading conflicts..."**: Conflicts panel is loading
- **"Cloning..."**: Creating a new draft version

---

## Error Handling

### Common Errors

**"Cannot modify final versions. Clone to draft first."**
- You tried to drag a match in a final version
- Solution: Click "Clone to Draft" button

**"Slot occupied"**
- You tried to drop a match on an occupied slot
- Solution: Choose an empty slot (green background)

**"Cannot modify assignments on a 'final' schedule version."**
- Backend rejected the move because version is final
- Solution: Clone to draft first

**"Failed to move assignment"**
- Network error or validation failure
- The error banner shows the backend's error message
- The grid and conflicts automatically refresh to ensure accuracy

**Dismissing Errors**:
- Click the "Dismiss" button on the error banner
- Or make another action (the error will clear automatically)

---

## Best Practices

### 1. Work in Drafts
- Always edit draft versions
- Finalize only when the schedule is ready for publication
- Once finalized, clone to draft if changes are needed

### 2. Check Conflicts After Each Move
- The conflicts panel updates automatically after each move
- Pay attention to ordering violations
- Resolve conflicts before finalizing

### 3. Use Version Cloning for Undo
- Before making major changes, clone the current draft
- This gives you a "save point" to return to
- Version history is your undo mechanism

### 4. Lock Important Assignments
- Manually-placed matches are automatically locked
- Locked matches won't be moved by auto-assign
- You can still move locked matches manually if needed

### 5. Refresh When in Doubt
- Click the "Refresh Conflicts" button to ensure data is current
- The system auto-refreshes after moves, but manual refresh is available

---

## Keyboard & Mouse Tips

### Mouse Actions
- **Click + Drag**: Move a match to a new slot
- **Hover**: See which slots are available (green background)
- **Drop**: Release mouse to save the move

### Browser Tips
- **Ctrl + Click** (on version selector): Open version in new tab
- **F5 / Ctrl + R**: Refresh page (will reload from server)
- **Ctrl + Z**: No built-in undo (use version cloning instead)

---

## Troubleshooting

### "Grid is empty"
- **Cause**: No slots generated yet
- **Solution**: Go back to main schedule page and click "Build Schedule"

### "No versions available"
- **Cause**: No schedule versions created
- **Solution**: Go to main schedule page and create a draft version

### "Drag doesn't work"
- **Possible causes**:
  1. Version is final (clone to draft)
  2. Another move is in progress (wait for save to complete)
  3. Browser compatibility issue (try Chrome/Edge/Firefox)

### "Conflicts don't update"
- **Cause**: Rare race condition or network issue
- **Solution**: Click "Refresh Conflicts" button

### "Match disappeared after move"
- **Cause**: Backend validation rejected the move
- **Solution**: Check error banner for details; grid auto-refreshes to show correct state

---

## Technical Notes

### Data Refresh Strategy
- **After every move**: Grid + conflicts automatically refetch
- **After clone**: New version loads automatically
- **Manual refresh**: Use "Refresh Conflicts" button

### Backend Integration
- All moves call: `PATCH /api/tournaments/{id}/schedule/assignments/{assignmentId}`
- Backend automatically sets `locked=true` on manual moves
- Backend blocks moves on final versions (returns 422 error)

### Browser Compatibility
- **Recommended**: Chrome 90+, Edge 90+, Firefox 88+
- **Drag/drop library**: @dnd-kit (modern, accessible)
- **State management**: Zustand (lightweight, performant)

---

## Support & Feedback

If you encounter issues:
1. Check the browser console for errors (F12 → Console tab)
2. Note the exact error message from the error banner
3. Try refreshing the page (F5)
4. If problem persists, report with:
   - Tournament ID
   - Version ID
   - Steps to reproduce
   - Screenshot of error banner

---

**Last Updated**: 2026-01-12  
**Version**: Phase 3E Initial Release

