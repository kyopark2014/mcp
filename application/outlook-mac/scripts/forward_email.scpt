on run argv
    -- First argument is now the path to the email config file
    set configPath to item 1 of argv
    
    -- Read email from config file
    set emailConfigFile to (open for access configPath)
    set userEmail to (read emailConfigFile)
    close access emailConfigFile
    
    -- Other arguments shifted by one
    set messageID to item 2 of argv
    set forwardTo to item 3 of argv
    set additionalText to ""
    if (count of argv) > 3 then
        set additionalText to item 4 of argv
    end if
    
    tell application "Microsoft Outlook"
        try
            set theMessage to message id messageID
            set forwardMessage to forward theMessage with opening window
            
            -- Add recipient
            tell forwardMessage
                make new recipient at forwardMessage with properties {email address:{address:forwardTo}}
                
                -- Add additional text if provided
                if additionalText is not "" then
                    set content of forwardMessage to additionalText & return & return & content of forwardMessage
                end if
            end tell
            
            -- Leave the forward window open for review before sending
            return "Forward created successfully. Please review and send manually."
        on error errMsg
            return "Error forwarding email: " & errMsg
        end try
    end tell
end run
