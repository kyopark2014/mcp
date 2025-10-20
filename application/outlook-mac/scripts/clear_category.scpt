on run argv
    -- First argument is email config file
    set userEmail to item 1 of argv
    set accountType to item 2 of argv
    
    -- Other arguments
    set messageIDInput to item 3 of argv
    set categoryName to item 4 of argv
    
    tell application "Microsoft Outlook"
        try
            -- Check if we have multiple message IDs (delimited by comma)
            if messageIDInput contains "," then
                set messageIDs to my split(messageIDInput, ",")
                set clearedCount to 0
                
                repeat with currentID in messageIDs
                    try
                        set theMessage to message id currentID
                        
                        -- If a specific category is provided, remove only that category
                        if categoryName is not "" then
                            -- Get current categories
                            set currentCategories to categories of theMessage
                            
                            -- Find the category object by name
                            set targetCategory to missing value
                            set allCategories to every category
                            repeat with c in allCategories
                                if name of c is categoryName then
                                    set targetCategory to c
                                    exit repeat
                                end if
                            end repeat
                            
                            -- If category exists, remove it from the message
                            if targetCategory is not missing value then
                                -- Create a new list without the target category
                                set newCategories to {}
                                repeat with c in currentCategories
                                    if name of c is not categoryName then
                                        copy c to end of newCategories
                                    end if
                                end repeat
                                
                                -- Apply the new categories list
                                set categories of theMessage to newCategories
                                set clearedCount to clearedCount + 1
                            end if
                        else
                            -- If no specific category is provided, clear all categories
                            set categories of theMessage to {}
                            set clearedCount to clearedCount + 1
                        end if
                    on error errMsg
                        -- Continue with next message if one fails
                        log "Error clearing category for message " & currentID & ": " & errMsg
                    end try
                end repeat
                
                if categoryName is not "" then
                    return "Successfully removed category '" & categoryName & "' from " & clearedCount & " of " & (count of messageIDs) & " emails"
                else
                    return "Successfully cleared all categories from " & clearedCount & " of " & (count of messageIDs) & " emails"
                end if
            else
                -- Single message ID
                set theMessage to message id messageIDInput
                
                -- If a specific category is provided, remove only that category
                if categoryName is not "" then
                    -- Get current categories
                    set currentCategories to categories of theMessage
                    
                    -- Find the category object by name
                    set targetCategory to missing value
                    set allCategories to every category
                    repeat with c in allCategories
                        if name of c is categoryName then
                            set targetCategory to c
                            exit repeat
                        end if
                    end repeat
                    
                    -- If category exists, remove it from the message
                    if targetCategory is not missing value then
                        -- Create a new list without the target category
                        set newCategories to {}
                        repeat with c in currentCategories
                            if name of c is not categoryName then
                                copy c to end of newCategories
                            end if
                        end repeat
                        
                        -- Apply the new categories list
                        set categories of theMessage to newCategories
                        return "Successfully removed category '" & categoryName & "' from email"
                    else
                        return "Category '" & categoryName & "' not found on email"
                    end if
                else
                    -- If no specific category is provided, clear all categories
                    set categories of theMessage to {}
                    return "Successfully cleared all categories from email"
                end if
            end if
        on error errMsg
            return "Error clearing categories: " & errMsg
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
