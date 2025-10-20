on run argv
    -- Process arguments: email address, account type, and message ID
    set userEmail to item 1 of argv
    
    -- Set default account type if not provided
    set accountType to "Exchange"
    if (count of argv) > 1 then
        set accountType to item 2 of argv
    end if
    
    -- Get message ID from arguments
    set messageID to item 3 of argv
    
    tell application "Microsoft Outlook"
        try
            set theMessage to message id messageID
            set emailSubject to subject of theMessage
            
            -- Try to get sender information safely
            set emailSender to "Unknown Sender"
            try
                set theSender to sender of theMessage
                set emailSender to name of theSender
            on error
                -- If we can't get the display name, try the email address
                try
                    set theSender to sender of theMessage
                    set emailSender to address of theSender
                on error
                    -- Keep the default "Unknown Sender"
                end try
            end try
            
            -- Get the received date
            set emailDate to time received of theMessage
            
            -- Get the content
            set emailContent to ""
            try
                set emailContent to plain text content of theMessage
            on error
                set emailContent to "Unable to retrieve content"
            end try
            
            set emailData to emailSubject & "||" & emailSender & "||" & emailDate & "||" & emailContent
            return emailData
        on error errMsg
            return "Error retrieving email: " & errMsg
        end try
    end tell
end run
