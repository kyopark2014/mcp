# Outlook Database Schema Documentation

## Overview

This document provides a comprehensive overview of the Outlook SQLite database schema used by the Outlook MCP Server. Understanding this schema is essential for formulating effective queries to retrieve email information.

## Key Tables

### Mail

The `Mail` table contains information about individual emails.

**Key Columns:**
- `Record_RecordID`: Unique identifier for the email
- `Message_NormalizedSubject`: Email subject
- `Message_SenderList`: Sender email address
- `Message_TimeReceived`: Timestamp when the email was received (Unix timestamp)
- `Message_ReadFlag`: Whether the email has been read (0 = unread, 1 = read)
- `Message_HasAttachment`: Whether the email has attachments (0 = no, 1 = yes)
- `Record_FlagStatus`: Flag status of the email (0 = not flagged, >0 = flagged)
- `Message_Preview`: Preview of the email content
- `Record_FolderID`: ID of the folder containing the email

### Folders

The `Folders` table contains information about email folders.

**Key Columns:**
- `Record_RecordID`: Unique identifier for the folder
- `Folder_Name`: Name of the folder
- `Folder_ParentID`: ID of the parent folder (for nested folders)
- `Record_AccountUID`: ID of the account the folder belongs to
- `Folder_FolderClass`: Class of the folder
- `Folder_SpecialFolderType`: Type of special folder (e.g., Inbox, Sent Items)

### AccountsExchange

The `AccountsExchange` table contains information about email accounts.

**Key Columns:**
- `Record_RecordID`: Unique identifier for the account
- `Account_EmailAddress`: Email address of the account

### Categories

The `Categories` table contains information about email categories.

**Key Columns:**
- `Record_RecordID`: Unique identifier for the category
- `Category_Name`: Name of the category
- `Record_AccountUID`: ID of the account the category belongs to
- `Category_BackgroundColor`: Color of the category

### Mail_Categories

The `Mail_Categories` table links emails to categories.

**Key Columns:**
- `Record_RecordID`: ID of the email (references Mail.Record_RecordID)
- `Category_RecordID`: ID of the category (references Categories.Record_RecordID)
- `Record_FolderID`: ID of the folder containing the email

## Common Relationships

1. **Emails and Folders**:
   - Each email in the `Mail` table belongs to a folder
   - The `Record_FolderID` in `Mail` corresponds to `Record_RecordID` in `Folders`

2. **Folders and Accounts**:
   - Each folder belongs to an account
   - The `Record_AccountUID` in `Folders` corresponds to `Record_RecordID` in `AccountsExchange`

3. **Emails and Categories**:
   - Emails can be assigned to categories through the `Mail_Categories` table
   - The `Record_RecordID` in `Mail_Categories` corresponds to `Record_RecordID` in `Mail`
   - The `Category_RecordID` in `Mail_Categories` corresponds to `Record_RecordID` in `Categories`

## Common Query Patterns

### 1. Basic Email Query

To retrieve basic email information:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 2. Emails with Folder Information

To retrieve emails with their folder information:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime,
       f.Folder_Name
FROM Mail m
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 3. Emails from a Specific Account

To retrieve emails from a specific account:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
WHERE f.Record_AccountUID = ?  -- Account ID
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 4. Unread Emails

To retrieve unread emails:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Message_ReadFlag = 0
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 5. Emails with Attachments

To retrieve emails with attachments:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Message_HasAttachment = 1
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 6. Flagged Emails

To retrieve flagged emails:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Record_FlagStatus > 0
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 7. Emails from a Specific Sender

To retrieve emails from a specific sender:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Message_SenderList LIKE '%example@example.com%'
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 8. Emails with a Specific Subject

To retrieve emails with a specific subject:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Message_NormalizedSubject LIKE '%meeting%'
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 9. Emails from a Specific Date Range

To retrieve emails from a specific date range:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Message_TimeReceived >= ? AND m.Message_TimeReceived <= ?  -- Unix timestamps
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 10. Emails in a Specific Folder

To retrieve emails from a specific folder:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime
FROM Mail m
WHERE m.Record_FolderID = ?  -- Folder ID
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 11. List All Categories

To list all available categories:

```sql
SELECT Category_Name, Record_RecordID
FROM Categories
ORDER BY Category_Name
```

### 12. Emails in a Specific Category

To retrieve emails in a specific category:

```sql
SELECT m.Record_RecordID, m.Message_NormalizedSubject, m.Message_SenderList,
       datetime(m.Message_TimeReceived, 'unixepoch') as ReceivedTime,
       f.Folder_Name
FROM Mail_Categories mc
JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
JOIN Mail m ON mc.Record_RecordID = m.Record_RecordID
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
WHERE c.Category_Name = ?  -- Category name
ORDER BY m.Message_TimeReceived DESC
LIMIT 10
```

### 13. Count of Emails in Each Category

To get a count of emails in each category:

```sql
SELECT c.Category_Name, COUNT(*) AS EmailCount
FROM Mail_Categories mc
JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
GROUP BY c.Category_Name
ORDER BY EmailCount DESC
```

## Best Practices

1. **Always use JOINs** when retrieving data from multiple tables
2. **Use LIMIT** to restrict the number of results returned
3. **Order by Message_TimeReceived DESC** to get the most recent emails first
4. **Use datetime(timestamp, 'unixepoch')** to convert Unix timestamps to readable dates
5. **Use LIKE with % wildcards** for partial matching of subjects and senders
6. **Use parameters (?)** for dynamic values to prevent SQL injection

## Common Filters

- **Unread emails**: `m.Message_ReadFlag = 0`
- **Read emails**: `m.Message_ReadFlag = 1`
- **Emails with attachments**: `m.Message_HasAttachment = 1`
- **Emails without attachments**: `m.Message_HasAttachment = 0`
- **Flagged emails**: `m.Record_FlagStatus > 0`
- **Unflagged emails**: `m.Record_FlagStatus = 0`
- **Today's emails**: `m.Message_TimeReceived >= [start_of_day] AND m.Message_TimeReceived <= [end_of_day]`
- **Emails from a specific sender**: `m.Message_SenderList LIKE '%sender@example.com%'`
- **Emails with a specific subject**: `m.Message_NormalizedSubject LIKE '%subject%'`
- **Emails in a specific category**: Use JOIN with Categories table and filter by Category_Name

## Advanced Queries

### Email Count by Folder

```sql
SELECT f.Folder_Name, COUNT(*) as EmailCount
FROM Mail m
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
GROUP BY f.Folder_Name
ORDER BY EmailCount DESC
```

### Email Volume by Month

```sql
SELECT strftime('%Y-%m', datetime(m.Message_TimeReceived, 'unixepoch')) as Month,
       COUNT(*) as EmailCount
FROM Mail m
GROUP BY Month
ORDER BY Month DESC
```

### Top Senders

```sql
SELECT m.Message_SenderList, COUNT(*) as EmailCount
FROM Mail m
GROUP BY m.Message_SenderList
ORDER BY EmailCount DESC
LIMIT 20
```

### Unread Email Count by Folder

```sql
SELECT f.Folder_Name, COUNT(*) as UnreadCount
FROM Mail m
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
WHERE m.Message_ReadFlag = 0
GROUP BY f.Folder_Name
ORDER BY UnreadCount DESC
```

### Emails in Categories with Folder Information

```sql
SELECT c.Category_Name, 
       m.Message_NormalizedSubject AS Subject, 
       m.Message_SenderList AS Sender,
       datetime(m.Message_TimeReceived, 'unixepoch') AS ReceivedTime,
       f.Folder_Name AS Folder
FROM Mail_Categories mc
JOIN Categories c ON mc.Category_RecordID = c.Record_RecordID
JOIN Mail m ON mc.Record_RecordID = m.Record_RecordID
JOIN Folders f ON m.Record_FolderID = f.Record_RecordID
ORDER BY c.Category_Name, m.Message_TimeReceived DESC
```

## Conclusion

This documentation provides a comprehensive overview of the Outlook database schema and common query patterns. Use this information to formulate effective queries for retrieving email information from the database.
