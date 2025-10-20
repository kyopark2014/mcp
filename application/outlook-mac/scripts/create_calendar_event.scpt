/**
 * create_calendar_event.scpt
 * 
 * Creates a new calendar event in Microsoft Outlook for Mac with robust error handling
 * 
 * Arguments:
 * argv[0] - Subject (string)
 * argv[1] - Start time (ISO format string: "2025-07-02T14:00:00")
 * argv[2] - End time (ISO format string: "2025-07-02T15:00:00")
 * argv[3] - Location (string, optional)
 * argv[4] - Description/body (string, optional)
 * argv[5] - Calendar ID (number, optional - uses default calendar if not specified)
 * argv[6] - Attendees (comma-separated email addresses, optional) - NOTE: Currently not supported
 * argv[7] - Is all-day event (boolean string "true"/"false", optional)
 */

function run(argv) {
    try {
        // Parse arguments
        var subject = argv[0];
        var startTimeStr = argv[1];
        var endTimeStr = argv[2];
        var location = argv[3] || "";
        var description = argv[4] || "";
        var calendarIdStr = argv[5] || "";
        var attendeesStr = argv[6] || "";
        var isAllDayStr = argv[7] || "false";
        
        // Validate required arguments
        if (!subject) {
            return JSON.stringify({
                error: "Subject is required",
                status: "error"
            });
        }
        
        if (!startTimeStr) {
            return JSON.stringify({
                error: "Start time is required",
                status: "error"
            });
        }
        
        if (!endTimeStr) {
            return JSON.stringify({
                error: "End time is required",
                status: "error"
            });
        }
        
        // Parse dates
        var startTime, endTime;
        try {
            startTime = new Date(startTimeStr);
            endTime = new Date(endTimeStr);
        } catch (error) {
            return JSON.stringify({
                error: "Invalid date format. Use ISO format (e.g., '2025-07-02T14:00:00')",
                status: "error"
            });
        }
        
        // Validate dates
        if (isNaN(startTime.getTime()) || isNaN(endTime.getTime())) {
            return JSON.stringify({
                error: "Invalid date format. Use ISO format (e.g., '2025-07-02T14:00:00')",
                status: "error"
            });
        }
        
        if (endTime <= startTime) {
            return JSON.stringify({
                error: "End time must be after start time",
                status: "error"
            });
        }
        
        // Parse isAllDay
        var isAllDay = (isAllDayStr.toLowerCase() === "true");
        
        // Check if Outlook is running and get application
        var outlook = Application("Microsoft Outlook");
        if (!outlook.running()) {
            return JSON.stringify({
                error: "Microsoft Outlook is not running",
                status: "error"
            });
        }
        
        // Get all calendars
        var allCalendars = outlook.calendars();
        
        // Find target calendar
        var targetCalendar = null;
        
        if (calendarIdStr) {
            // Convert string ID to number for comparison
            var calendarId = Number(calendarIdStr);
            
            // Find calendar by ID
            for (var i = 0; i < allCalendars.length; i++) {
                if (allCalendars[i].id() == calendarId) {
                    targetCalendar = allCalendars[i];
                    break;
                }
            }
            
            if (!targetCalendar) {
                return JSON.stringify({
                    error: "Calendar not found",
                    requested_id: calendarIdStr,
                    status: "error"
                });
            }
        } else {
            // Use a named calendar by default (instead of the first one)
            var defaultCalendarFound = false;
            
            // First try to find a calendar named "Calendar"
            for (var i = 0; i < allCalendars.length; i++) {
                var calName = allCalendars[i].name();
                if (calName === "Calendar") {
                    targetCalendar = allCalendars[i];
                    defaultCalendarFound = true;
                    break;
                }
            }
            
            // If no "Calendar" found, look for any calendar with a non-empty name
            if (!defaultCalendarFound) {
                for (var i = 0; i < allCalendars.length; i++) {
                    var calName = allCalendars[i].name();
                    if (calName && calName.length > 0) {
                        targetCalendar = allCalendars[i];
                        defaultCalendarFound = true;
                        break;
                    }
                }
            }
            
            // If still no named calendar found, use the first one as a last resort
            if (!defaultCalendarFound && allCalendars.length > 0) {
                targetCalendar = allCalendars[0];
            } else if (!defaultCalendarFound) {
                return JSON.stringify({
                    error: "No calendars found",
                    status: "error"
                });
            }
        }
        
        // Create new calendar event
        var newEvent = outlook.CalendarEvent({
            subject: subject,
            startTime: startTime,
            endTime: endTime,
            location: location,
            content: description,
            allDayFlag: isAllDay
        });
        
        // Add event to calendar
        targetCalendar.calendarEvents.push(newEvent);
        
        // Process attendees if provided
        var attendeeNotice = "";
        if (attendeesStr && attendeesStr.length > 0) {
            // Parse the attendees string to get a count
            var attendeeEmails = attendeesStr.split(",");
            var attendeeCount = 0;
            for (var i = 0; i < attendeeEmails.length; i++) {
                if (attendeeEmails[i].trim()) {
                    attendeeCount++;
                }
            }
            
            // Add a notice about attendees not being supported
            attendeeNotice = `Note: ${attendeeCount} attendee(s) were provided but could not be added. Adding attendees is not currently supported.`;
        }
        
        // Return success with event details
        return JSON.stringify({
            status: "success",
            event_id: newEvent.id(),
            calendar_id: targetCalendar.id(),
            calendar_name: targetCalendar.name(),
            subject: subject,
            start_time: startTime.toISOString(),
            end_time: endTime.toISOString(),
            location: location,
            is_all_day: isAllDay,
            attendee_notice: attendeeNotice
        });
        
    } catch (error) {
        // Catch any unexpected errors
        return JSON.stringify({
            error: "Error creating calendar event: " + (error.message || "Unknown error"),
            stack: error.stack || "",
            status: "error"
        });
    }
}
