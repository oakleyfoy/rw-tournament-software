# Total Court Minutes Calculation

## Current Calculation (backend/app/routes/phase1_status.py, lines 47-71)

```python
# Calculate total court minutes
total_court_minutes = 0
for day in active_days:
    if not day.start_time or not day.end_time:
        errors.append(f"Start time or end time not set on active day {day.date}")
        continue
    
    if day.courts_available < 1:
        errors.append(f"Courts not set on active day {day.date}")
        continue
    
    # Calculate minutes between start and end time
    start_datetime = day.start_time
    end_datetime = day.end_time
    
    # Convert time to minutes since midnight
    start_minutes = start_datetime.hour * 60 + start_datetime.minute
    end_minutes = end_datetime.hour * 60 + end_datetime.minute
    
    if end_minutes <= start_minutes:
        errors.append(f"End time must be greater than start time on active day {day.date}")
        continue
    
    day_minutes = end_minutes - start_minutes
    total_court_minutes += day_minutes * day.courts_available
```

## Formula

For each active day:
1. Calculate minutes in the day: `(end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute)`
2. Multiply by number of courts: `day_minutes * courts_available`
3. Sum across all active days: `total_court_minutes += day_minutes * courts_available`

## Example

- Day 1: 8:00 AM to 6:00 PM (10 hours = 600 minutes) with 2 courts = 1,200 minutes
- Day 2: 9:00 AM to 5:00 PM (8 hours = 480 minutes) with 3 courts = 1,440 minutes
- Total: 2,640 minutes

