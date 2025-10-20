#!/usr/bin/osascript -l JavaScript

function run(argv) {
    // Get calendar ID - keep as string initially for loose comparison
    var calendarIDStr = argv[0];
    var calendarID = Number(calendarIDStr); // Convert to number for comparison
    
    // Optional date range parameters
    var startDateStr = "";
    var endDateStr = "";
    
    if (argv.length > 1) {
        startDateStr = argv[1];
    }
    
    if (argv.length > 2) {
        endDateStr = argv[2];
    }
    
    try {
        var outlook = Application('Microsoft Outlook');
        var allCalendars = outlook.calendars();
        
        // Debug info
        var calendarInfo = [];
        for (var i = 0; i < allCalendars.length; i++) {
            calendarInfo.push({
                index: i,
                id: allCalendars[i].id(),
                name: allCalendars[i].name()
            });
        }
        
        // Find calendar by ID using loose equality (==) instead of strict equality (===)
        var targetCalendar = null;
        for (var i = 0; i < allCalendars.length; i++) {
            var currentId = allCalendars[i].id();
            // Use loose equality to compare (allows string "546" to match number 546)
            if (currentId == calendarID) {
                targetCalendar = allCalendars[i];
                break;
            }
        }
        
        // If not found by loose equality, try by index as fallback
        if (!targetCalendar && !isNaN(calendarID) && calendarID >= 0 && calendarID < allCalendars.length) {
            targetCalendar = allCalendars[calendarID];
        }
        
        if (!targetCalendar) {
            return JSON.stringify({ 
                error: "Calendar not found", 
                requested_id: calendarIDStr,
                requested_id_type: typeof calendarIDStr,
                requested_id_as_number: calendarID,
                total_calendars: allCalendars.length,
                available_calendars: calendarInfo
            });
        }
        
        // Get events from the calendar
        var allEvents = targetCalendar.calendarEvents();
        var filteredEvents = allEvents;
        
        // Filter by date range if provided
        if (startDateStr && endDateStr) {
            var startDate = new Date(startDateStr);
            var endDate = new Date(endDateStr);
            
            filteredEvents = [];
            for (var i = 0; i < allEvents.length; i++) {
                var event = allEvents[i];
                var eventStart = new Date(event.startTime());
                var eventEnd = new Date(event.endTime());
                
                if ((eventStart >= startDate && eventStart <= endDate) || 
                    (eventEnd >= startDate && eventEnd <= endDate)) {
                    filteredEvents.push(event);
                }
            }
        }
        
        // Format event data as JSON
        var eventArray = [];
        
        for (var i = 0; i < filteredEvents.length; i++) {
            var event = filteredEvents[i];
            var eventContent = "";
            
            try {
                eventContent = event.content();
            } catch (e) {
                // Content might not be available
            }
            
            eventArray.push({
                subject: event.subject(),
                id: event.id(),
                start_time: event.startTime().toString(),
                end_time: event.endTime().toString(),
                location: event.location(),
                is_all_day: event.allDayFlag(),
                content: eventContent
            });
        }
        
        // Use JSON.stringify to handle all escaping automatically
        return JSON.stringify(eventArray);
    } catch (error) {
        return JSON.stringify({ 
            error: "Error accessing calendar events: " + error.message,
            stack: error.stack
        });
    }
}