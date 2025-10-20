on run argv

    -- First argument is email config file
    set userEmail to item 1 of argv
    set accountType to item 2 of argv
    
    -- Other arguments shifted by one
    set messageIDInput to item 3 of argv
    
    tell application "Microsoft Outlook"
        try
            -- Check if we have multiple message IDs (delimited by comma)
            if messageIDInput contains "," then
                set messageIDs to my split(messageIDInput, ",")
                set deletedCount to 0
                
                repeat with currentID in messageIDs
                    try
                        set theMessage to message id currentID
                        delete theMessage
                        set deletedCount to deletedCount + 1
                    on error errMsg
                        -- Continue with next message if one fails
                        log "Error deleting message " & currentID & ": " & errMsg
                    end try
                end repeat
                
                return "Successfully deleted " & deletedCount & " of " & (count of messageIDs) & " emails"
            else
                -- Single message ID
                set theMessage to message id messageIDInput
                delete theMessage
                return "Email deleted successfully"
            end if
        on error errMsg
            return "Error deleting email: " & errMsg
        end try
    end tell
end run

-- Helper function to split a string by delimiter
on split(theString, theDelimiter)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to theDelimiter
    set theItems to every text item of theString
    set AppleScript's text item delimiters to oldDelimiters
    return theItems
end split
