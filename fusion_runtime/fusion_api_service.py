"""
Fusion 360 API 客户端 - 通过 Socket 连接到本地 Fusion 实例

通信协议：
- 基于 TCP Socket (localhost:9999)
- 命令格式：JSON ({"action": "...", ...})
- 响应格式：JSON
- 超时设置：默认30秒

启动 Fusion API 服务方法：
1. Fusion 360 → 实用工具 → 脚本和加载项
2. 浏览到 fusion_api_server.py
3. 点击运行
4. 然后运行 Python pipeline
"""

import json
import socket
import time
from typing import Dict, Any, List, Optional
from pathlib import Path


class FusionAPIClient:
    """Fusion 360 API 客户端 - 通过 Socket 与 Fusion 通信"""
    
    def __init__(self, host: str = "localhost", port: int = 9999, timeout: int = 30):
        """初始化客户端
        
        Args:
            host: Fusion API 服务器地址
            port: Fusion API 服务器端口
            timeout: 连接和响应超时（秒）
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        # Connection is per-request; we don't keep a long-lived socket.
        self.connected = False
        
    def connect(self) -> bool:
        """连接到 Fusion API 服务
        
        Returns:
            连接是否成功
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.close()
            self.connected = True
            print(f"✅ 已连接到 Fusion API ({self.host}:{self.port})")
            return True
        except socket.timeout:
            print(f"⏱️  连接超时: {self.timeout}秒内无响应")
            self.connected = False
            return False
        except ConnectionRefusedError:
            print(f"❌ 连接被拒绝 - 确保 Fusion 中 API 服务正在运行")
            print(f"   请在 Fusion 中: 实用工具 → 脚本和加载项 → fusion_api_server.py → 运行")
            self.connected = False
            return False
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """断开连接"""
        self.connected = False
        print("✅ 已断开连接")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected
    
    def ping(self) -> bool:
        """测试与 Fusion API 的连接
        
        Returns:
            是否能正常通信
        """
        result = self.execute_command({"action": "ping"})
        return result.get("status") == "success"
    
    def execute_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """发送命令到 Fusion
        
        Args:
            command: 要执行的命令（字典格式）
        
        Returns:
            Fusion 的响应结果
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))

            # 发送命令
            cmd_json = json.dumps(command) + "\n"
            sock.sendall(cmd_json.encode('utf-8'))

            # 接收响应
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                # 检查是否收到完整的JSON（以\n结尾）
                if response.endswith(b'\n'):
                    break

            sock.close()
            if not response:
                return {"status": "error", "message": "empty response from server"}

            return json.loads(response.decode('utf-8'))
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def configure(self, *, project_root: str) -> Dict[str, Any]:
        """向 Fusion 端服务发送一次性配置（例如项目根目录）。

        这用于让 Fusion 端能 import 本仓库内的模块（fusion_runtime 等）。
        """
        return self.execute_command({"action": "configure", "project_root": project_root})

    def execute_capability(
        self,
        *,
        function_name: str,
        inputs: Dict[str, Any],
        step: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """请求 Fusion 端执行一个 capability（与 ExecutorBase 语义一致）。"""
        return self.execute_command(
            {
                "action": "execute_capability",
                "function_name": function_name,
                "inputs": inputs,
                "step": step or {},
                "context": context or {},
            }
        )
    
    def execute_script_content(
        self,
        *,
        name: str,
        script: str,
        run_id: Optional[str] = None,
        export_like: bool = False,
    ) -> Dict[str, Any]:
        """执行脚本内容（直接发送到 Fusion 端执行）。

        Args:
            name: 脚本名（用于日志/调试）
            script: Python 源码字符串
            run_id: 可选；用于 Fusion 端按 run_id 切换/绑定 active design
            export_like: 可选；用于 Fusion 端对导出类操作做 gating（仅 run success 才允许）
        """

        command: Dict[str, Any] = {
            "action": "execute_script",
            "script": script,
            "name": name,
        }
        if run_id is not None:
            command["run_id"] = run_id
        if export_like:
            command["export_like"] = True

        return self.execute_command(command)

    def execute_script(
        self,
        script_path: str,
        *,
        run_id: Optional[str] = None,
        export_like: bool = False,
    ) -> Dict[str, Any]:
        """执行脚本文件"""
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                script_content = f.read()
        except Exception as e:
            return {"status": "error", "message": f"无法读取脚本: {e}"}

        return self.execute_script_content(
            name=Path(script_path).stem,
            script=script_content,
            run_id=run_id,
            export_like=export_like,
        )
    
    def execute_steps(self, steps: list) -> Dict[str, Any]:
        """执行一系列步骤"""
        command = {
            "action": "execute_steps",
            "steps": steps
        }
        
        return self.execute_command(command)
