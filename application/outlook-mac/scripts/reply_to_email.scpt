on run argv

    -- First argument is email config file
    set userEmail to item 1 of argv
    
    -- Other arguments shifted by one
    set messageID to item 3 of argv
    set inputText to item 4 of argv
    
    tell application "Microsoft Outlook"
        try
            set theMessage to message id messageID
            
            -- Create a reply that includes the original message (without opening window)
            set replyMessage to reply to theMessage
            
            -- Get the original content that Outlook automatically includes
            set originalContent to content of replyMessage
            
            -- Create HTML content with the formatted text - just the text with <br> tags
            set replyHtml to inputText & originalContent
            
            -- Set the content as HTML
            set content of replyMessage to replyHtml
            
            -- Send the reply immediately
            send replyMessage
            
            return "Draft reply created. You need to send it manually after review."
        on error errMsg
            return "Error sending reply: " & errMsg
        end try
    end tell
end run
