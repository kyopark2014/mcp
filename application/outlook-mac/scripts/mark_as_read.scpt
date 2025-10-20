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
                set markedCount to 0
                
                repeat with currentID in messageIDs
                    try
                        set theMessage to message id currentID
                        set is read of theMessage to true
                        set markedCount to markedCount + 1
                    on error errMsg
                        -- Continue with next message if one fails
                        log "Error marking message " & currentID & " as read: " & errMsg
                    end try
                end repeat
                
                return "Successfully marked " & markedCount & " of " & (count of messageIDs) & " emails as read"
            else
                -- Single message ID
                set theMessage to message id messageIDInput
                set is read of theMessage to true
                return "Email marked as read successfully"
            end if
        on error errMsg
            return "Error marking email as read: " & errMsg
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
