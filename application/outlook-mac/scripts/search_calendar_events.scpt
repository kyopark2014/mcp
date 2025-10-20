#!/usr/bin/osascript -l JavaScript

function run(argv) {
    // Get search query and max results
    var searchQuery = argv[0] || "";
    var maxResults = 100;
    var searchDate = null;
    
    if (argv.length > 1) {
        maxResults = parseInt(argv[1]);
    }
    
    // Check if the query is a date format
    if (searchQuery.toLowerCase() === "today") {
        searchDate = new Date();
    } else if (searchQuery.match(/^\d{4}-\d{2}-\d{2}$/)) {
        // Format YYYY-MM-DD
        searchDate = new Date(searchQuery);
    } else if (searchQuery.match(/^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(\s*,\s*\d{4})?$/i)) {
        // Format like "April 24" or "April 24, 2025"
        searchDate = new Date(searchQuery);
    }
    
    try {
        var outlook = Application('Microsoft Outlook');
        var allCalendars = outlook.calendars();
        
        var matchingEvents = [];
        var resultCount = 0;
        
        // Search across all calendars
        for (var i = 0; i < allCalendars.length; i++) {
            try {
                var calendar = allCalendars[i];
                var events = calendar.calendarEvents();
                
                for (var j = 0; j < events.length; j++) {
                    // Check if we've reached the maximum results
                    if (resultCount >= maxResults) {
                        break;
                    }
                    
                    var event = events[j];
                    var eventSubject = event.subject() || "";
                    var eventLocation = event.location() || "";
                    var eventContent = "";
                    var startTime = event.startTime();
                    var endTime = event.endTime();
                    
                    try {
                        eventContent = event.content() || "";
                    } catch (e) {
                        // Content might not be available
                        eventContent = "";
                    }
                    
                    var isMatch = false;
                    
                    // Date-based matching
                    if (searchDate) {
                        var eventDate = new Date(startTime);
                        
                        // Compare year, month, and day
                        if (eventDate.getFullYear() === searchDate.getFullYear() &&
                            eventDate.getMonth() === searchDate.getMonth() &&
                            eventDate.getDate() === searchDate.getDate()) {
                            isMatch = true;
                        }
                    } 
                    // Text-based matching
                    else if (eventSubject.indexOf(searchQuery) !== -1 || 
                        eventLocation.indexOf(searchQuery) !== -1 || 
                        eventContent.indexOf(searchQuery) !== -1) {
                        isMatch = true;
                    }
                    
                    if (isMatch) {
                        // Add to matching events with calendar name
                        matchingEvents.push({
                            subject: eventSubject,
                            id: event.id(),
                            start_time: startTime.toString(),
                            end_time: endTime.toString(),
                            location: eventLocation,
                            is_all_day: event.allDayFlag(),
                            calendar_name: calendar.name() || "",
                            calendar_id: calendar.id()
                        });
                        
                        resultCount++;
                    }
                }
            } catch (calendarError) {
                // Skip calendars that can't be accessed
                continue;
            }
            
            // Check if we've reached the maximum results
            if (resultCount >= maxResults) {
                break;
            }
        }
        
        // Use JSON.stringify to handle all escaping automatically
        return JSON.stringify(matchingEvents);
    } catch (error) {
        return JSON.stringify({ 
            error: "Error searching calendar events: " + error.message,
            stack: error.stack
        });
    }
}