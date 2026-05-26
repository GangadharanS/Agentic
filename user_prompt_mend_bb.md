# Query Prompt
1. List the security vulnerabilities of direct libraries of project `bbf4c3d2-6651-4b0f-98a0-d455782e5341` via mcp_tool
2. Create a JIRA Bug ticket for all these vulnerabilities and add components as `whitesource` via mcp_tool 
3. clone the repo in local.
4. go through the code base of repo `Trimble Connect Files Service` in Bitbucket `master` branch
5. Create a branch by mentioning name as the created JIRA ticket
6. Apply the fixes for security vulnerabilities in the local cloned repo identified in step 1
7. run `gradle build` and fix the issues if there are any
8. commit and push the changes
9. raise PR for the change. 