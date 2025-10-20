#!/usr/bin/osascript -l JavaScript

function run(argv) {
    try {
        var outlook = Application('Microsoft Outlook');
        var allCalendars = outlook.calendars();
        
        var calendarArray = [];
        
        for (var i = 0; i < allCalendars.length; i++) {
            var calendar = allCalendars[i];
            calendarArray.push({
                name: calendar.name(),
                id: calendar.id(),
                index: i
            });
        }
        
        // Use JSON.stringify to handle all escaping automatically
        return JSON.stringify(calendarArray);
    } catch (error) {
        return JSON.stringify({ 
            error: "Error accessing calendars: " + error.message,
            stack: error.stack
        });
    }
}
