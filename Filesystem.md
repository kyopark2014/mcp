# Filesystem MCP Server

[Filesystem MCP Server](https://www.npmjs.com/package/@modelcontextprotocol/server-filesystem)을 이용하여 파일에 대한 정보를 가져올 수 있습니다. 좀 더 자세한 정보는 [Filesystem](https://sebastian-petrus.medium.com/mcp-server-claude-work-with-local-files-594f332a7084)를 참조합니다.

아래와 같이 필요한 패키지를 설치합니다.

```text
npx @modelcontextprotocol/server-filesystem
```

아래와 같이 config를 설정합니다. 파일 경로는 적절히 수정합니다. 

```java
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
	    "@modelcontextprotocol/server-filesystem",
        "/Users/ksdyb/Documents"
      ]
    }
  }
}
```


이때 얻어진 tool에 대한 정보는 아래와 같습니다.

```java
[
   StructuredTool("name=""read_file",
   "description=""Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages if the file cannot be read. Use this tool when you need to examine the contents of a single file. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         }
      },
      "required":[
         "path"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x103254c20>),
   "StructuredTool(name=""read_multiple_files",
   "description=""Read the contents of multiple files simultaneously. This is more efficient than reading files one by one when you need to analyze or compare multiple files. Each file's content is returned with its path as a reference. Failed reads for individual files won't stop the entire operation. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "paths":{
            "type":"array",
            "items":{
               "type":"string"
            }
         }
      },
      "required":[
         "paths"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52ca0>),
   "StructuredTool(name=""write_file",
   "description=""Create a new file or completely overwrite an existing file with new content. Use with caution as it will overwrite existing files without warning. Handles text content with proper encoding. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         },
         "content":{
            "type":"string"
         }
      },
      "required":[
         "path",
         "content"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52c00>),
   "StructuredTool(name=""edit_file",
   "description=""Make line-based edits to a text file. Each edit replaces exact line sequences with new content. Returns a git-style diff showing the changes made. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         },
         "edits":{
            "type":"array",
            "items":{
               "type":"object",
               "properties":{
                  "oldText":{
                     "type":"string",
                     "description":"Text to search for - must match exactly"
                  },
                  "newText":{
                     "type":"string",
                     "description":"Text to replace with"
                  }
               },
               "required":[
                  "oldText",
                  "newText"
               ],
               "additionalProperties":false
            }
         },
         "dryRun":{
            "type":"boolean",
            "default":false,
            "description":"Preview changes using git-style diff format"
         }
      },
      "required":[
         "path",
         "edits"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52b60>),
   "StructuredTool(name=""create_directory",
   "description=""Create a new directory or ensure a directory exists. Can create multiple nested directories in one operation. If the directory already exists, this operation will succeed silently. Perfect for setting up directory structures for projects or ensuring required paths exist. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         }
      },
      "required":[
         "path"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52ac0>),
   "StructuredTool(name=""list_directory",
   "description=""Get a detailed listing of all files and directories in a specified path. Results clearly distinguish between files and directories with [FILE] and [DIR] prefixes. This tool is essential for understanding directory structure and finding specific files within a directory. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         }
      },
      "required":[
         "path"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52a20>),
   "StructuredTool(name=""directory_tree",
   "description=""Get a recursive tree view of files and directories as a JSON structure. Each entry includes 'name', 'type' (file/directory), and 'children' for directories. Files have no children array, while directories always have a children array (which may be empty). The output is formatted with 2-space indentation for readability. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         }
      },
      "required":[
         "path"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52980>),
   "StructuredTool(name=""move_file",
   "description=""Move or rename files and directories. Can move files between directories and rename them in a single operation. If the destination exists, the operation will fail. Works across different directories and can be used for simple renaming within the same directory. Both source and destination must be within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "source":{
            "type":"string"
         },
         "destination":{
            "type":"string"
         }
      },
      "required":[
         "source",
         "destination"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b528e0>),
   "StructuredTool(name=""search_files",
   "description=""Recursively search for files and directories matching a pattern. Searches through all subdirectories from the starting path. The search is case-insensitive and matches partial names. Returns full paths to all matching items. Great for finding files when you don't know their exact location. Only searches within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         },
         "pattern":{
            "type":"string"
         },
         "excludePatterns":{
            "type":"array",
            "items":{
               "type":"string"
            },
            "default":[
               
            ]
         }
      },
      "required":[
         "path",
         "pattern"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52840>),
   "StructuredTool(name=""get_file_info",
   "description=""Retrieve detailed metadata about a file or directory. Returns comprehensive information including size, creation time, last modified time, permissions, and type. This tool is perfect for understanding file characteristics without reading the actual content. Only works within allowed directories.",
   "args_schema="{
      "type":"object",
      "properties":{
         "path":{
            "type":"string"
         }
      },
      "required":[
         "path"
      ],
      "additionalProperties":false,
      "$schema":"http://json-schema.org/draft-07/schema#"
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b527a0>),
   "StructuredTool(name=""list_allowed_directories",
   "description=""Returns the list of directories that this server is allowed to access. Use this to understand which directories are available before trying to access files.",
   "args_schema="{
      "type":"object",
      "properties":{
         
      },
      "required":[
         
      ]
   },
   "response_format=""content_and_artifact",
   coroutine=<function convert_mcp_tool_to_langchain_tool.<locals>.call_tool at 0x127b52700>)
]
```

이제 "파일의 갯수를 알려주세요."를 입력하고 결과를 확인합니다.

![image](https://github.com/user-attachments/assets/04bb29db-17c8-42c0-a277-927ddfd95249)

"noname.png 파일의 크기는?"로 입력합니다.

![image](https://github.com/user-attachments/assets/1b95935e-ff63-42a9-a670-b129597391be)

"test.txt 파일을 생성하고, 파일에 "안녕하세요."라고 입력하세요."라고 입력하면 파일을 생성할 수 있습니다.

![image](https://github.com/user-attachments/assets/4fe08e44-5535-4769-bccf-763a3dde7109)
