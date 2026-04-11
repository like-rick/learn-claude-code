---
name: python-style
description: Python coding style guide for clean code
---

# Python Style Guide

## Naming Conventions

- Use `snake_case` for functions and variables
- Use `PascalCase` for class names
- Use `UPPER_CASE` for constants

## Code Structure

- Keep functions under 50 lines when possible
- Use type hints for function parameters
- Add docstrings for all public functions

## Example

```python
def calculate_total(items: list[dict]) -> float:
    """Calculate total price of items."""
    return sum(item["price"] for item in items)
```
