# Query Prompt
1. Extract the content from the doc - `requirement.pdf`. use requirement.pdf as file_path
2. Extract the links related to figma in the `requirement.pdf` and get the contents using `login_figma_and_get_content`
3. Access JIRA to create EPIC for the given summary in the `requirement.pdf` with project key as TCPLT and add components as `whitesource`
Provide the description with proper text formatting with mandatory bullet points (not .md file format, just .txt file format).   
4. For UX reference, access the figma link given in the document if there are any and add description based on that. add the specific figma content hyperlink in teh description.
5. The other reference links in the document should added in the description as well.
