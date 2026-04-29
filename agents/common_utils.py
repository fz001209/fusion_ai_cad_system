"""
Agent 共享工具函数

目的：消除各个 Agent 中重复的 IO 和 LLM 调用代码
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List


def read_json(path: Path) -> Any:
    """读取 JSON 文件（UTF-8编码）"""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件（UTF-8编码，自动创建父目录）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_defined_vars(steps: List[Dict[str, Any]]) -> set[str]:
    """从步骤列表中收集所有已定义的变量名"""
    defined: set[str] = set()
    for step in steps:
        capture = step.get("capture")
        if isinstance(capture, Mapping):
            vars_map = capture.get("vars")
            if isinstance(vars_map, Mapping):
                for var_name in vars_map.keys():
                    if isinstance(var_name, str):
                        defined.add(var_name)
        outputs = step.get("outputs")
        if isinstance(outputs, Mapping):
            for var_name in outputs.keys():
                if isinstance(var_name, str):
                    defined.add(var_name)
    return defined


def read_yaml(path: Path) -> Any:
    """读取 YAML 文件（UTF-8编码）"""
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def call_llm(prompt: str, *, model: str | None = None, temperature: float = 0) -> str | None:
    """
    调用 OpenAI API（统一的 LLM 调用接口）
    
    Args:
        prompt: 提示词文本
        model: 模型名称（可选，默认从环境变量读取）
        temperature: 温度参数（默认0，确定性输出）
    
    Returns:
        LLM 响应文本，失败返回 None
    
    环境变量:
        OPENAI_API_KEY: OpenAI API 密钥（必需）
        OPENAI_BASE_URL: API 基础 URL（可选，默认 https://api.openai.com）
        OPENAI_MODEL: 默认模型（可选，默认 gpt-4o-mini）
    """
    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        
        import urllib.request
        
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip().rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        
        url = f"{base_url}/chat/completions"
        
        if model is None:
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
        
        obj = json.loads(raw)
        content = obj["choices"][0]["message"]["content"]
        return content.strip()
    
    except Exception:
        return None


def extract_json_from_llm_response(text: str) -> Dict[str, Any] | None:
    """
    从 LLM 响应中提取 JSON
    
    支持多种格式：
    1. 直接的 JSON 对象
    2. Markdown 代码块中的 JSON (```json ... ```)
    3. 代码块中的 JSON (``` ... ```)
    
    Args:
        text: LLM 响应文本
    
    Returns:
        解析后的 JSON 对象，失败返回 None
    """
    if not text:
        return None
    
    # 1. 尝试直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    
    # 2. 尝试提取 Markdown 代码块
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    
    # 3. 尝试查找第一个 { ... } 块
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    
    return None
