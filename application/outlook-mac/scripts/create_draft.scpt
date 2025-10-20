on run argv
    -- First argument is email config file
    set userEmail to item 1 of argv
    
    -- Other arguments shifted by one
    set recipientEmail to item 5 of argv
    set emailSubject to item 3 of argv
    set emailBody to item 4 of argv
    
    tell application "Microsoft Outlook"
        try
            -- Create a new message
            set newMessage to make new outgoing message with properties {subject:emailSubject}

            -- Add recipient
            tell newMessage
                make new recipient with properties {email address:{address:recipientEmail}}
            end tell            

            -- Set the content as HTML
            set content of newMessage to emailBody
            
            -- Open the message for editing (this will allow manual recipient addition)
            open newMessage
            
            return "Draft created successfully. Check outlook window for furthe editing"
        on error errMsg
            return "Error creating draft: " & errMsg
        end try
    end tell
end run
