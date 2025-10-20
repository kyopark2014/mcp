on run {userEmail, accountType, messageId, savePath}
    try
        tell application "Microsoft Outlook"
            -- Get the specified account
            set targetAccount to missing value
            if userEmail is not "" then
                if accountType is "Exchange" then
                    set targetAccount to exchange account userEmail
                else if accountType is "POP3" then
                    set targetAccount to pop account userEmail
                else if accountType is "IMAP" then
                    set targetAccount to imap account userEmail
                end if
            end if
            
            -- Find the message
            set targetMessage to missing value
            if targetAccount is not missing value then
                set targetMessage to first message of inbox of targetAccount whose id = messageId
            else
                set targetMessage to first message of inbox whose id = messageId
            end if
            
            if targetMessage is missing value then
                return "Error: Message not found"
            end if
            
            -- Debug info
            log "Found message with subject: " & (subject of targetMessage)
            log "Number of attachments: " & (count of attachments of targetMessage)
            
            -- Get attachments
            set attachmentList to {}
            set savedFiles to {}
            
            -- Process each attachment
            repeat with anAttachment in attachments of targetMessage
                try
                    set attachmentName to name of anAttachment
                    set attachmentSize to file size of anAttachment
                    set attachmentType to content type of anAttachment
                    
                    -- Debug info
                    log "Processing attachment: " & attachmentName
                    log "Size: " & attachmentSize
                    log "Type: " & attachmentType
                    
                    -- Create full save path for this attachment
                    set fullSavePath to savePath & "/" & attachmentName
                    
                    -- Debug info
                    log "Saving to: " & fullSavePath
                    
                    -- Save the attachment
                    try
                        -- Create a temporary file path
                        set tempPath to (path to temporary items as text) & attachmentName
                        
                        -- First save to temp location
                        save anAttachment in tempPath
                        
                        -- Then move to final location using shell command
                        do shell script "mv " & quoted form of (POSIX path of tempPath) & " " & quoted form of fullSavePath
                        
                        -- Add to list of saved files with details
                        set savedFileInfo to attachmentName & "|" & attachmentSize & "|" & attachmentType & "|" & fullSavePath
                        copy savedFileInfo to end of savedFiles
                        
                        -- Debug info
                        log "Successfully saved: " & attachmentName
                    on error errSaveMsg
                        set errorInfo to "Error saving " & attachmentName & ": " & errSaveMsg
                        copy errorInfo to end of savedFiles
                        
                        -- Debug info
                        log "Failed to save: " & errorInfo
                    end try
                on error errMsg
                    -- If there's an error with one attachment, continue with others
                    set errorInfo to "Error processing " & attachmentName & ": " & errMsg
                    copy errorInfo to end of savedFiles
                    
                    -- Debug info
                    log "Error: " & errorInfo
                end try
            end repeat
            
            -- Return the list of saved files
            return (items of savedFiles) as string
            
        end tell
    on error errMsg
        return "Error: " & errMsg
    end try
end run
