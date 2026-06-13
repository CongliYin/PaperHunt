"""通用工具函数：配置加载、归一化、缓存、安全 HTTP 请求"""
import json
import math
import os
import time
from typing import Any, Optional

import requests


# ==================== 配置加载 ====================

def load_yaml(path: str) -> dict:
    """加载 YAML 配置文件。"""
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency PyYAML. Install dependencies with: pip install requests PyYAML"
        ) from exc

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ==================== 数值工具 ====================

def log_normalize(value: float, max_val: float) -> float:
    """对数归一化到 [0, 1]。
    value <= 0 返回 0；value >= max_val 返回 1。
    使用 log(x+1) / log(max_val+1) 公式。
    """
    if value is None or value <= 0:
        return 0.0
    if max_val <= 0:
        return 0.0
    result = math.log(value + 1) / math.log(max_val + 1)
    return min(max(result, 0.0), 1.0)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """截断到 [lo, hi]。"""
    return max(lo, min(hi, value))


# ==================== 缓存读写 ====================

def load_cache(path: str) -> dict:
    """加载 JSON 缓存文件，不存在则返回空 dict。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(path: str, data: dict) -> None:
    """保存 dict 到 JSON 缓存文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== 安全 HTTP 请求 ====================

def safe_get(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 15,
    max_retries: int = 2,
    sleep_after: float = 0.0,
) -> Optional[Any]:
    """带重试和超时的 GET 请求，返回解析后的 JSON 或 None。
    任何异常都会被吞掉并返回 None（V1 失败容错策略：跳过该信号）。
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                if sleep_after > 0:
                    time.sleep(sleep_after)
                return resp.json()
            elif resp.status_code == 429:
                if attempt >= max_retries:
                    last_err = "HTTP 429"
                    break
                # 限流：等更久后重试
                time.sleep(3.0 * (attempt + 1))
                continue
            else:
                last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(1.0 * (attempt + 1))
    if sleep_after > 0:
        time.sleep(sleep_after)
    return None
