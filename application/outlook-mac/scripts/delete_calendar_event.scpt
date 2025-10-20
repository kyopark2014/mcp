/**
 * delete_calendar_event.scpt
 * 
 * Deletes a calendar event from Microsoft Outlook for Mac
 * 
 * Arguments:
 * argv[0] - Event ID (number)
 */

function run(argv) {
    try {
        // Parse arguments
        var eventIdStr = argv[0];
        
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
        var eventDetails = null;
        
        for (var i = 0; i < allCalendars.length; i++) {
            var calendar = allCalendars[i];
            var events = calendar.calendarEvents();
            
            for (var j = 0; j < events.length; j++) {
                var event = events[j];
                if (event.id() === eventId) {
                    targetEvent = event;
                    // Capture event details before deletion
                    eventDetails = {
                        subject: event.subject(),
                        start_time: event.startTime().toISOString(),
                        end_time: event.endTime().toISOString(),
                        location: event.location() || "",
                        calendar_name: calendar.name()
                    };
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
        
        // Delete the event
        targetEvent.delete();
        
        return JSON.stringify({
            status: "success",
            message: "Calendar event deleted successfully",
            event_id: eventId,
            deleted_event: eventDetails
        });
        
    } catch (error) {
        return JSON.stringify({
            status: "error",
            error: "Failed to delete calendar event: " + error.message
        });
    }
}
