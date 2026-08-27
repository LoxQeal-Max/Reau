"""LLM 客户端 - 支持太石网关多模态调用"""
from __future__ import annotations
import base64
import json
import time
from typing import Optional, Union
from urllib.request import Request, urlopen
from urllib.error import URLError


class LLMClient:
    """通用 LLM 客户端 - 支持多模态消息格式"""

    def __init__(self, config: dict):
        self.config = config
        self.api_base = config.get("api_base", "")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "")
        self.headers = config.get("headers", {})
        self.format = config.get("format", "openai")
        self.supports_vision = config.get("supports_vision", False)

    def chat(self, messages: list,
             system_prompt: str = "",
             temperature: float = 0.7,
             max_tokens: int = 2000) -> Optional[str]:
        """发送对话请求"""
        if self.format == "openai":
            return self._chat_openai_format(messages, system_prompt, temperature, max_tokens)
        else:
            return self._chat_custom_format(messages, system_prompt)

    def chat_with_image(self, messages: list,
                        image_data: Optional[bytes] = None,
                        system_prompt: str = "",
                        temperature: float = 0.7,
                        max_tokens: int = 2000) -> Optional[str]:
        """发送带图片的对话请求（多模态）"""
        if not image_data or not self.supports_vision:
            return self.chat(messages, system_prompt, temperature, max_tokens)

        # 将最后一条 user 消息的 content 转为多模态格式
        img_b64 = base64.b64encode(image_data).decode("utf-8")
        image_content = {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}"
            }
        }

        new_messages = []
        for msg in messages:
            if msg["role"] == "user" and msg == messages[-1]:
                # 最后一条 user 消息：文本 + 图片
                text_content = msg["content"] if isinstance(msg["content"], str) else ""
                new_content = [
                    {"type": "text", "text": text_content},
                    image_content,
                ]
                new_messages.append({
                    "role": msg["role"],
                    "content": new_content,
                })
            else:
                new_messages.append(msg)

        return self._chat_openai_format(new_messages, system_prompt, temperature, max_tokens)

    def _chat_openai_format(self, messages: list,
                            system_prompt: str,
                            temperature: float,
                            max_tokens: int) -> Optional[str]:
        """OpenAI 兼容格式请求（支持多模态 content）"""
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = dict(self.headers)
        if "Authorization" not in headers and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.setdefault("Content-Type", "application/json")

        url = f"{self.api_base.rstrip('/')}/chat/completions"
        return self._send_request(url, payload, headers)

    def _chat_custom_format(self, messages: list,
                            system_prompt: str) -> Optional[str]:
        """自定义格式请求"""
        user_message = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                content = msg["content"]
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            user_message = part.get("text", "")
                            break
                break

        custom_config = self.config.get("custom_format", {})
        if custom_config:
            template = custom_config.get("request_template", {})
            payload = {}
            for key, value in template.items():
                if isinstance(value, str) and "{" in value:
                    payload[key] = value.replace("{prompt}", user_message)
                    payload[key] = payload[key].replace("{api_key}", self.api_key)
                    payload[key] = payload[key].replace("{session_id}", str(int(time.time())))
                else:
                    payload[key] = value
        else:
            payload = {
                "prompt": user_message,
                "system": system_prompt,
                "apiKey": self.api_key,
            }

        headers = dict(self.headers)
        headers.setdefault("Content-Type", "application/json")

        url = self.api_base
        return self._send_request(url, payload, headers)

    def _send_request(self, url: str, payload: dict, headers: dict) -> Optional[str]:
        """发送 HTTP 请求"""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(url, data=data, headers=headers, method="POST")

            with urlopen(req, timeout=60) as response:
                response_data = response.read().decode("utf-8")
                result = json.loads(response_data)

            return self._parse_response(result)

        except URLError as e:
            print(f"LLM 请求失败: {e}")
            return None
        except Exception as e:
            print(f"LLM 响应解析失败: {e}")
            return None

    def _parse_response(self, response: dict) -> Optional[str]:
        """解析响应内容"""
        if "choices" in response:
            choices = response["choices"]
            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                    return "\n".join(parts).strip()
                return content.strip() if content else None

        for key in ["result", "answer", "content", "message", "data"]:
            if key in response:
                value = response[key]
                if isinstance(value, str):
                    return value.strip()
                elif isinstance(value, dict):
                    for subkey in ["result", "answer", "content", "text"]:
                        if subkey in value:
                            return str(value[subkey]).strip()

        for key, value in response.items():
            if isinstance(value, str) and len(value) > 10:
                return value.strip()

        print(f"无法解析 LLM 响应: {json.dumps(response, ensure_ascii=False, indent=2)}")
        return None


def create_llm_client(config_name: str = "taishi") -> Optional[LLMClient]:
    """根据配置创建 LLM 客户端"""
    try:
        from config.llm_config import TAISHI_LLM, DINGTALK_LLM, OTHER_PROVIDERS

        if config_name in ("taishi", "dingtalk"):
            config = TAISHI_LLM
        elif config_name in OTHER_PROVIDERS:
            config = OTHER_PROVIDERS[config_name]
        else:
            raise ValueError(f"未知的配置: {config_name}")

        if not config.get("enabled", False):
            print("LLM 未启用")
            return None

        if not config.get("api_key"):
            print("LLM API Key 未配置")
            return None

        return LLMClient(config)

    except ImportError:
        print("配置模块导入失败")
        return None
    except Exception as e:
        print(f"创建 LLM 客户端失败: {e}")
        return None
