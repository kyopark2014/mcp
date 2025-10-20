/**
 * update_calendar_event.scpt
 * 
 * Updates an existing calendar event in Microsoft Outlook for Mac
 * 
 * Arguments:
 * argv[0] - Event ID (number)
 * argv[1] - New subject (string, optional - empty string to keep current)
 * argv[2] - New start time (ISO format string, optional - empty string to keep current)
 * argv[3] - New end time (ISO format string, optional - empty string to keep current)
 * argv[4] - New location (string, optional - empty string to keep current)
 * argv[5] - New description/body (string, optional - empty string to keep current)
 * argv[6] - New is all-day flag (boolean string "true"/"false", optional - empty string to keep current)
 */

function run(argv) {
    try {
        // Parse arguments
        var eventIdStr = argv[0];
        var newSubject = argv[1] || "";
        var newStartTimeStr = argv[2] || "";
        var newEndTimeStr = argv[3] || "";
        var newLocation = argv[4] || "";
        var newDescription = argv[5] || "";
        var newIsAllDayStr = argv[6] || "";
        
        // Validate required arguments
        if (!eventIdStr) {
            return JSON.stringify({
                status: "error",
                error: "Event ID is required"
            });
        }
        
        var eventId = parseInt(eventIdStr);
        if (isNaN(eventId)) {
            return JSON.stringify({
                status: "error",
                error: "Invalid event ID: must be a number"
            });
        }
        
        var outlook = Application('Microsoft Outlook');
        
        // Find the event by ID
        var allCalendars = outlook.calendars();
        var targetEvent = null;
        
        for (var i = 0; i < allCalendars.length; i++) {
            var calendar = allCalendars[i];
            var events = calendar.calendarEvents();
            
            for (var j = 0; j < events.length; j++) {
                var event = events[j];
                if (event.id() === eventId) {
                    targetEvent = event;
                    break;
                }
            }
            if (targetEvent) break;
        }
        
        if (!targetEvent) {
            return JSON.stringify({
                status: "error",
                error: "Event not found with ID: " + eventId
            });
        }
        
        // Update fields if new values are provided
        if (newSubject) {
            targetEvent.subject = newSubject;
        }
        
        if (newStartTimeStr) {
            try {
                var newStartDate = new Date(newStartTimeStr);
                if (isNaN(newStartDate.getTime())) {
                    return JSON.stringify({
                        status: "error",
                        error: "Invalid start time format. Use ISO format like '2025-07-02T14:00:00'"
                    });
                }
                targetEvent.startTime = newStartDate;
            } catch (e) {
                return JSON.stringify({
                    status: "error",
                    error: "Error parsing start time: " + e.message
                });
            }
        }
        
        if (newEndTimeStr) {
            try {
                var newEndDate = new Date(newEndTimeStr);
                if (isNaN(newEndDate.getTime())) {
                    return JSON.stringify({
                        status: "error",
                        error: "Invalid end time format. Use ISO format like '2025-07-02T15:00:00'"
                    });
                }
                targetEvent.endTime = newEndDate;
            } catch (e) {
                return JSON.stringify({
                    status: "error",
                    error: "Error parsing end time: " + e.message
                });
            }
        }
        
        if (newLocation) {
            targetEvent.location = newLocation;
        }
        
        if (newDescription) {
            targetEvent.content = newDescription;
        }
        
        if (newIsAllDayStr) {
            var newIsAllDay = newIsAllDayStr.toLowerCase() === "true";
            targetEvent.allDayFlag = newIsAllDay;
        }
        
        // Save the changes
        try {
            targetEvent.save();
        } catch (saveError) {
            // Check for the specific error message that occurs despite successful updates
            if (saveError.message && saveError.message.includes("A file or directory where the object should be saved is required")) {
                // This is a known issue where the update succeeds but Outlook's API returns this error
                // The event is actually updated successfully despite this error
                console.log("Ignoring known save error that occurs despite successful update");
            } else {
                // For any other error, propagate it
                throw saveError;
            }
        }
        
        return JSON.stringify({
            status: "success",
            message: "Calendar event updated successfully",
            event_id: eventId,
            updated_fields: {
                subject: newSubject || null,
                start_time: newStartTimeStr || null,
                end_time: newEndTimeStr || null,
                location: newLocation || null,
                description: newDescription || null,
                is_all_day: newIsAllDayStr || null
            }
        });
        
    } catch (error) {
        return JSON.stringify({
            status: "error",
            error: "Failed to update calendar event: " + error.message
        });
    }
}
