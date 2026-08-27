"""LLM 配置文件 - 太石 LLM 网关 (公司内部)"""

# 太石 LLM 网关主配置
TAISHI_LLM = {
    "enabled": True,
    "name": "太石LLM网关",
    "api_base": "https://yyds.yy2hd.com/v1",
    "api_key": "1hV1aIavrPprZJQU0cA68cD5F4B249CfA432B510E1A7290a",  # TODO: 替换为完整的 Key（从令牌管理页面复制）
    "model": "claude-sonnet-4.6",
    "headers": {
        "Content-Type": "application/json",
    },
    "format": "openai",
    "supports_vision": True,
}

# 兼容旧代码：dingtalk 指向太石网关
DINGTALK_LLM = TAISHI_LLM

# 其他可选 LLM 配置
OTHER_PROVIDERS = {
    "taishi_haiku": {
        "api_base": "https://yyds.yy2hd.com/v1",
        "api_key": "",
        "model": "claude-haiku-4-5",
        "format": "openai",
        "supports_vision": True,
    },
    "taishi_opus": {
        "api_base": "https://yyds.yy2hd.com/v1",
        "api_key": "",
        "model": "claude-opus-4.6",
        "format": "openai",
        "supports_vision": True,
    },
    "qwen": {
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen-vl-max",
        "format": "openai",
        "supports_vision": True,
    },
    "deepseek": {
        "api_base": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "format": "openai",
        "supports_vision": False,
    },
}
