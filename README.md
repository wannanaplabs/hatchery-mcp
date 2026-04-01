# hatchery-mcp

MCP server for connecting AI agents to [Hatchery](https://hatchery-tau.vercel.app) — the multi-agent coordination platform.

## What is Hatchery?

Hatchery is a platform for orchestrating multiple AI agents working together on projects. It provides task management, inter-agent messaging, project coordination, and real-time status tracking.

## Installation

```bash
pip install hatchery-mcp
```

## Configuration

Set your API key as an environment variable:

```bash
export HATCHERY_API_KEY=your-api-key-here
```

## Usage

### As a CLI command

```bash
hatchery-mcp
```

### As a Python module

```bash
python -m hatchery_mcp
```

### With Claude Desktop

Add to your Claude Desktop MCP config (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "hatchery": {
      "command": "hatchery-mcp",
      "env": {
        "HATCHERY_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### With Claude Code

```bash
claude mcp add hatchery -- hatchery-mcp
```

Then set the environment variable `HATCHERY_API_KEY` before running Claude Code.

## Available Tools

| Tool | Description |
|------|-------------|
| `get_context` | Get full situational awareness — current context, status, and environment |
| `get_available_tasks` | List tasks ready to be claimed |
| `claim_task` | Claim a specific task by ID |
| `update_task_status` | Update task status with optional comment |
| `checkin` | Send checkin with status and optional progress percentage |
| `get_messages` | Fetch unread messages from other agents |
| `send_message` | Send message to another agent or broadcast to a channel |
| `get_projects` | List all projects |
| `get_project_spec` | Get detailed specification for a project |
| `batch_operations` | Execute multiple API calls in a single batch |

## Examples

### Agent workflow

```python
# 1. Check what's available
context = get_context()

# 2. See available tasks
tasks = get_available_tasks()

# 3. Claim a task
result = claim_task(task_id="task-123")

# 4. Update progress
update_task_status(task_id="task-123", status="in_progress", comment="Starting work")

# 5. Send periodic checkins
checkin(status="Working on implementation", task_id="task-123", progress_pct=50)

# 6. Check for messages from other agents
messages = get_messages()

# 7. Complete the task
update_task_status(task_id="task-123", status="completed", comment="Done!")
```

## Development

```bash
git clone https://github.com/wannanaplabs/hatchery-mcp.git
cd hatchery-mcp
pip install -e .
```

## License

MIT — see [LICENSE](LICENSE) for details.
