from __future__ import annotations

import asyncio
import typing
import json

import openai
import openai.types.chat.chat_completion as chat_completion

from .. import api
from ....core import entities as core_entities
from ... import entities as llm_entities
from ...session import entities as session_entities


class OpenAIChatCompletion(api.LLMAPIRequester):
    client: openai.AsyncClient

    async def initialize(self):
        self.client = openai.AsyncClient(
            api_key="",
            base_url=self.ap.cfg_mgr.data["openai_config"]["reverse_proxy"],
            timeout=self.ap.cfg_mgr.data["process_message_timeout"],
        )

    async def _req(
        self,
        args: dict,
    ) -> chat_completion.ChatCompletion:
        self.ap.logger.debug(f"req chat_completion with args {args}")
        return await self.client.chat.completions.create(**args)

    async def _make_msg(
        self,
        chat_completion: chat_completion.ChatCompletion,
    ) -> llm_entities.Message:
        chatcmpl_message = chat_completion.choices[0].message.dict()

        message = llm_entities.Message(**chatcmpl_message)

        return message

    async def _closure(
        self,
        req_messages: list[dict],
        conversation: session_entities.Conversation,
        user_text: str = None,
        function_ret: str = None,
    ) -> llm_entities.Message:
        self.client.api_key = conversation.use_model.token_mgr.get_token()

        args = self.ap.cfg_mgr.data["completion_api_params"].copy()
        args["model"] = conversation.use_model.name

        tools = await self.ap.tool_mgr.generate_tools_for_openai(conversation)
        # tools = [
        #     {
        #         "type": "function",
        #         "function": {
        #             "name": "get_current_weather",
        #             "description": "Get the current weather in a given location",
        #             "parameters": {
        #                 "type": "object",
        #                 "properties": {
        #                     "location": {
        #                         "type": "string",
        #                         "description": "The city and state, e.g. San Francisco, CA",
        #                     },
        #                     "unit": {
        #                         "type": "string",
        #                         "enum": ["celsius", "fahrenheit"],
        #                     },
        #                 },
        #                 "required": ["location"],
        #             },
        #         },
        #     }
        # ]
        if tools:
            args["tools"] = tools

        # 设置此次请求中的messages
        messages = req_messages
        args["messages"] = messages

        # 发送请求
        resp = await self._req(args)

        # 处理请求结果
        message = await self._make_msg(resp)

        return message

    async def request(
        self, query: core_entities.Query, conversation: session_entities.Conversation
    ) -> typing.AsyncGenerator[llm_entities.Message, None]:
        """请求"""

        pending_tool_calls = []

        req_messages = [
            m.dict(exclude_none=True) for m in conversation.prompt.messages
        ] + [m.dict(exclude_none=True) for m in conversation.messages]

        # req_messages.append({"role": "user", "content": str(query.message_chain)})

        msg = await self._closure(req_messages, conversation)

        yield msg

        pending_tool_calls = msg.tool_calls

        req_messages.append(msg.dict(exclude_none=True))

        while pending_tool_calls:
            for tool_call in pending_tool_calls:
                func = tool_call.function

                parameters = json.loads(func.arguments)

                func_ret = await self.ap.tool_mgr.execute_func_call(
                    query, func.name, parameters
                )

                msg = llm_entities.Message(
                    role="tool", content=json.dumps(func_ret, ensure_ascii=False), tool_call_id=tool_call.id
                )

                yield msg

                req_messages.append(msg.dict(exclude_none=True))

            # 处理完所有调用，继续请求
            msg = await self._closure(req_messages, conversation)

            yield msg

            pending_tool_calls = msg.tool_calls

            req_messages.append(msg.dict(exclude_none=True))
