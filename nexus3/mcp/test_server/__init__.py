"""MCP test server for development and testing.

A full-featured MCP server with tools, resources, and prompts for testing
the client implementation.

Usage:
    python -m nexus3.mcp.test_server

Tools provided:
    - echo: Echo back a message
    - get_time: Get current date/time
    - add: Add two numbers
    - slow_operation: Simulate a slow operation (for progress testing)

Resources provided:
    - file:///readme.txt: Project readme file (text/plain)
    - file:///config.json: Project configuration (application/json)
    - file:///data/users.csv: User database export (text/csv)

Prompts provided:
    - greeting: Generate a greeting message
    - code_review: Review code for issues
    - summarize: Summarize text content

Utilities:
    - ping: Health check endpoint
"""
