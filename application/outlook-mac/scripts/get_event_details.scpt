#!/usr/bin/osascript -l JavaScript

function run(argv) {
    // Get event ID - keep as string initially for loose comparison
    var eventIDStr = argv[0];
    var eventID = Number(eventIDStr); // Convert to number for comparison
    
    try {
        var outlook = Application('Microsoft Outlook');
        var allCalendars = outlook.calendars();
        
        // Search for the event across all calendars
        var targetEvent = null;
        var calendarName = "";
        var calendarId = null;
        
        for (var i = 0; i < allCalendars.length; i++) {
            try {
                var calendar = allCalendars[i];
                var events = calendar.calendarEvents();
                
                for (var j = 0; j < events.length; j++) {
                    var event = events[j];
                    var currentId = event.id();
                    
                    // Use loose equality to compare (allows string "346" to match number 346)
                    if (currentId == eventID) {
                        targetEvent = event;
                        calendarName = calendar.name() || "";
                        calendarId = calendar.id();
                        break;
                    }
                }
                
                if (targetEvent) {
                    break;
                }
            } catch (calendarError) {
                // Skip calendars that can't be accessed
                continue;
            }
        }
        
        if (!targetEvent) {
            return JSON.stringify({ 
                error: "Event not found",
                requested_id: eventIDStr,
                requested_id_type: typeof eventIDStr,
                requested_id_as_number: eventID
            });
        }
        
        // Get event details
        var eventDetails = {
            subject: targetEvent.subject(),
            id: targetEvent.id(),
            start_time: targetEvent.startTime().toString(),
            end_time: targetEvent.endTime().toString(),
            location: targetEvent.location(),
            is_all_day: targetEvent.allDayFlag(),
            calendar_name: calendarName,
            calendar_id: calendarId,
            organizer: "",
            attendees: []
        };
        
        // Get content if available
        try {
            eventDetails.content = targetEvent.content();
        } catch (e) {
            eventDetails.content = null;
        }
        
        // Get organizer if available
        try {
            eventDetails.organizer = targetEvent.organizer();
        } catch (e) {
            // Organizer might not be available
        }
        
        // Get free/busy status if available
        try {
            eventDetails.free_busy_status = targetEvent.freeBusyStatus();
        } catch (e) {
            eventDetails.free_busy_status = "unknown";
        }
        
        // Get my response status
        // Since there's no direct property for this, we'll use freeBusyStatus as a proxy
        // and add more logic if we discover better properties
        try {
            var fbStatus = targetEvent.freeBusyStatus();
            if (fbStatus === "busy") {
                eventDetails.my_response = "accepted";
            } else if (fbStatus === "tentative") {
                eventDetails.my_response = "tentative";
            } else if (fbStatus === "free") {
                eventDetails.my_response = "none";
            } else if (fbStatus === "outOfOffice") {
                eventDetails.my_response = "accepted_out_of_office";
            } else {
                eventDetails.my_response = "unknown";
            }
        } catch (e) {
            eventDetails.my_response = "unknown";
        }
        
        // Get attendees if available
        try {
            var attendees = targetEvent.attendees();
            var attendeeList = [];
            
            for (var k = 0; k < attendees.length; k++) {
                try {
                    var attendee = attendees[k];
                    var attendeeInfo = {
                        name: attendee.name() || "",
                        email: attendee.email() || ""
                    };
                    
                    // Get response status if available
                    try {
                        attendeeInfo.status = attendee.status();
                    } catch (e) {
                        attendeeInfo.status = "unknown";
                    }
                    
                    attendeeList.push(attendeeInfo);
                } catch (attendeeError) {
                    // Skip attendees that can't be accessed
                    continue;
                }
            }
            
            eventDetails.attendees = attendeeList;
        } catch (e) {
            // Attendees might not be available
        }
        
        // Use JSON.stringify to handle all escaping automatically
        return JSON.stringify(eventDetails);
    } catch (error) {
        return JSON.stringify({ 
            error: "Error getting event details: " + error.message,
            stack: error.stack
        });
    }
}