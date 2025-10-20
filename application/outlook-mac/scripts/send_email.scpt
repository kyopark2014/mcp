on run argv
    -- First argument is email config file
    set userEmail to item 1 of argv
    
    -- Other arguments remain the same but shifted by one
    set recipientEmail to item 5 of argv
    set emailSubject to item 3 of argv
    set emailBody to item 4 of argv
    
    tell application "Microsoft Outlook"
        try
            -- Create a new message
            set newMessage to make new outgoing message with properties {subject:emailSubject}
            
            -- Replace \n with actual line breaks in the content
            set formattedBody to my replaceEscapedNewlines(emailBody)
            
            -- Set the content
            set content of newMessage to formattedBody
            
            -- Add recipient
            tell newMessage
                make new recipient with properties {email address:{address:recipientEmail}}
            end tell
            
            -- Send the message
            send newMessage
            
            return "Email sent successfully to " & recipientEmail
        on error errMsg
            return "Error sending email: " & errMsg
        end try
    end tell
end run

-- Helper function to replace escaped newlines with actual newlines
on replaceEscapedNewlines(theText)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to "\\n"
    set textItems to text items of theText
    set AppleScript's text item delimiters to return
    set newText to textItems as string
    set AppleScript's text item delimiters to oldDelimiters
    return newText
end replaceEscapedNewlines
