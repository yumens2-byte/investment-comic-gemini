Side prompts:
- System prompt: loaded at runtime from the Notion page `NOTION_SIDE_SYSTEM_ID`
  (adapters/notion/prompt_loader.py), following the main convention of not committing
  generation prompts to a public repository.
- User prompt: `user_side.j2` — structure only (echo values, beats, schema); no canon text.
