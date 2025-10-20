on run argv
    -- First argument is email config file
    set userEmail to item 1 of argv
    set accountType to item 2 of argv
    
    -- Other arguments
    set messageIDInput to item 3 of argv
    set categoryName to item 4 of argv
    
    tell application "Microsoft Outlook"
        try
            -- First check if the category exists
            set categoryExists to false
            set allCategories to every category
            
            repeat with currentCategory in allCategories
                if name of currentCategory is categoryName then
                    set categoryExists to true
                    exit repeat
                end if
            end repeat
            
            -- If category doesn't exist, create it
            if not categoryExists then
                -- Create a new category with default color
                make new category with properties {name:categoryName}
                log "Created new category: " & categoryName
            end if
            
            -- Check if we have multiple message IDs (delimited by comma)
            if messageIDInput contains "," then
                set messageIDs to my split(messageIDInput, ",")
                set categorizedCount to 0
                
                repeat with currentID in messageIDs
                    try
                        set theMessage to message id currentID
                        -- Find the category object by name
                        set targetCategory to missing value
                        repeat with c in allCategories
                            if name of c is categoryName then
                                set targetCategory to c
                                exit repeat
                            end if
                        end repeat
                        
                        -- Assign the category to the message
                        if targetCategory is not missing value then
                            set categories of theMessage to targetCategory
                            set categorizedCount to categorizedCount + 1
                        else
                            error "Could not find category named '" & categoryName & "'"
                        end if
                    on error errMsg
                        -- Continue with next message if one fails
                        log "Error categorizing message " & currentID & ": " & errMsg
                    end try
                end repeat
                
                return "Successfully assigned category '" & categoryName & "' to " & categorizedCount & " of " & (count of messageIDs) & " emails"
            else
                -- Single message ID
                set theMessage to message id messageIDInput
                -- Find the category object by name
                set targetCategory to missing value
                repeat with c in allCategories
                    if name of c is categoryName then
                        set targetCategory to c
                        exit repeat
                    end if
                end repeat
                
                -- Assign the category to the message
                if targetCategory is not missing value then
                    set categories of theMessage to targetCategory
                else
                    error "Could not find category named '" & categoryName & "'"
                end if
                return "Successfully assigned category '" & categoryName & "' to email"
            end if
        on error errMsg
            return "Error assigning category: " & errMsg
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
