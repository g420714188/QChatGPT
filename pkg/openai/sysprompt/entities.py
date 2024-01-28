from __future__ import annotations

import typing
import pydantic

from ...openai import entities


class Prompt(pydantic.BaseModel):
    """供AI使用的Prompt"""

    name: str

    messages: list[entities.Message]
