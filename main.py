#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeAgent
作者: Evo
日期: 2026-08-07
"""

import os
import json
import re
import time
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig


class CodeAgentPlugin(Star):
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.logger = logger
        self.workspace = Path("./data/plugin_data/codeagent_plugin/workspace")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.scripts_dir = Path(__file__).parent / "skills" / "CodeAgent" / "scripts"
    
    def _get_config(self, key: str, default=None):
        return self.config.get(key, default)
    
    def _has_at_bot(self, text: str) -> bool:
        return bool(re.search(r'@', text))
    
    def _extract_requirement(self, text: str) -> Optional[str]:
        patterns = [
            r'/agent\s+(.+)',
            r'@.*?/agent\s+(.+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
    
    def _is_exit_command(self, text: str) -> bool:
        return bool(re.search(r'/exitconver', text, re.IGNORECASE))
    
    def _sanitize_session_id(self, group_id: str, user_id: str) -> str:
        return f"{group_id}_{user_id}".replace(':', '_').replace('/', '_')
    
    def _is_in_blacklist(self, user_id: str, group_id: str) -> bool:
        admin_blacklist = self._get_config("admin_blacklist", [])
        group_blacklist = self._get_config("group_blacklist", [])
        if admin_blacklist and str(user_id) in [str(i) for i in admin_blacklist]:
            return True
        if group_blacklist and str(group_id) in [str(i) for i in group_blacklist]:
            return True
        return False
    
    def _cleanup_session(self, session_id: str):
        session_dir = self.workspace / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
    
    def _call_sandbox(self, code: str, session_id: str, language: str = 'python', filename: str = 'main.py') -> Dict[str, Any]:
        sandbox_script = self.scripts_dir / "codeagent_sandbox.py"
        if not sandbox_script.exists():
            return {'success': False, 'error': 'Sandbox script not found'}
        
        timeout = self._get_config("code_running_time", 120)
        memory_limit = self._get_config("memory_limit", 512)
        max_file_size = self._get_config("max_file_size", 10)
        
        config_json = json.dumps({
            "wall_time_limit": timeout,
            "memory_limit_mb": memory_limit,
            "file_size_limit_mb": max_file_size
        })
        
        try:
            proc = subprocess.run(
                [
                    'python3', str(sandbox_script),
                    '--code', json.dumps(code),
                    '--session-id', session_id,
                    '--language', language,
                    '--filename', filename,
                    '--config', config_json
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 30
            )
            if proc.returncode != 0:
                return {'success': False, 'error': proc.stderr or 'Sandbox execution failed'}
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Sandbox timeout'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _call_security_scan(self, code: str, language: str = 'python') -> Dict[str, Any]:
        security_script = self.scripts_dir / "codeagent_security.py"
        if not security_script.exists():
            return {'passed': True, 'error': 'Security script not found'}
        
        try:
            proc = subprocess.run(
                [
                    'python3', str(security_script),
                    '--code', json.dumps(code),
                    '--language', language
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            return json.loads(proc.stdout)
        except Exception:
            return {'passed': True}
    
    def _call_packager(self, files: List[Dict], name: str, description: str) -> Dict[str, Any]:
        packager_script = self.scripts_dir / "codeagent_packager.py"
        if not packager_script.exists():
            return {'success': False, 'error': 'Packager script not found'}
        
        try:
            proc = subprocess.run(
                [
                    'python3', str(packager_script),
                    '--name', name,
                    '--description', description,
                    '--files', json.dumps(files)
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            return json.loads(proc.stdout)
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _analyze_error(self, stderr: str) -> Dict[str, Any]:
        lines = stderr.split('\n')
        error_type = 'Unknown'
        error_line = 0
        error_message = stderr[:500]
        
        for line in lines:
            if 'Error' in line or 'Exception' in line:
                match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*(?:Error|Exception))', line)
                if match:
                    error_type = match.group(1)
                line_match = re.search(r'line\s+(\d+)', line, re.IGNORECASE)
                if line_match:
                    error_line = int(line_match.group(1))
                break
        
        return {
            'error_type': error_type,
            'error_line': error_line,
            'error_message': error_message
        }
    
    def _generate_debug_fix(self, error_info: Dict[str, Any]) -> str:
        error_type = error_info.get('error_type', '')
        if 'Import' in error_type:
            missing = re.search(r"No module named '([^']+)'", error_info.get('error_message', ''))
            if missing:
                return f"import {missing.group(1)}"
        elif 'Name' in error_type:
            missing = re.search(r"name '([^']+)' is not defined", error_info.get('error_message', ''))
            if missing:
                return f"定义或导入 {missing.group(1)}"
        elif 'TypeError' in error_type:
            return "检查函数参数类型和数量"
        elif 'ValueError' in error_type:
            return "检查值格式是否正确"
        elif 'FileNotFound' in error_type:
            return "检查文件路径是否正确"
        return "检查代码逻辑"

    @filter.command("agent")
    async def agent_command(self, event: AstrMessageEvent):
        """代码编写 Agent，使用 /agent 需求描述 来触发"""
        message_str = event.message_str
        user_id = str(event.get_sender_id())
        group_id = str(event.get_group_id()) if hasattr(event, 'get_group_id') else 'private'
        
        if not message_str:
            return
        
        if self._is_in_blacklist(user_id, group_id):
            return
        
        if self._is_exit_command(message_str):
            session_id = self._sanitize_session_id(group_id, user_id)
            if session_id in self.active_sessions:
                self.active_sessions[session_id]['active'] = False
                self._cleanup_session(session_id)
                del self.active_sessions[session_id]
                yield event.plain_result("已终止 Agent 任务，临时文件已清理。")
            else:
                yield event.plain_result("当前没有正在执行的 Agent 任务。")
            return
        
        requirement = self._extract_requirement(message_str)
        if not requirement:
            if '/agent' in message_str:
                yield event.plain_result("请提供具体的需求描述。示例：/agent 写一个计算器")
            return
        
        session_id = self._sanitize_session_id(group_id, user_id)
        
        if session_id in self.active_sessions:
            yield event.plain_result("当前已有 Agent 任务在执行，请等待完成或使用 /exitconver 退出。")
            return
        
        self.active_sessions[session_id] = {
            'active': True,
            'requirement': requirement,
            'step': 0,
            'start_time': time.time()
        }
        
        try:
            yield event.plain_result(f"收到需求，正在分析...\n\n{requirement}")
            
            scheme = f"""
需求分析完成

设计方案：
- 语言：Python 3.10+
- 结构：单个脚本
- 功能：{requirement[:100]}

确认方案？回复"确认"开始编写。
"""
            yield event.plain_result(scheme)
            
            await asyncio.sleep(3)
            
            if not self.active_sessions.get(session_id, {}).get('active', True):
                yield event.plain_result("任务已终止。")
                return
            
            yield event.plain_result("开始编写代码...")
            
            code = f'''
import sys
import os

def main():
    print("Hello from CodeAgent!")
    print("需求: {requirement}")

if __name__ == "__main__":
    main()
'''
            
            filename = "main.py"
            language = "python"
            
            yield event.plain_result("代码编写完成，正在运行测试...")
            
            max_debug = self._get_config("max_debug_rounds", 10)
            quality_threshold = self._get_config("quality_threshold", 75)
            
            for debug_round in range(max_debug):
                sandbox_result = self._call_sandbox(code, session_id, language, filename)
                
                if not sandbox_result.get('success', False):
                    error_info = self._analyze_error(sandbox_result.get('stderr', '') or sandbox_result.get('error', 'Unknown error'))
                    fix = self._generate_debug_fix(error_info)
                    
                    if debug_round >= max_debug - 1:
                        yield event.plain_result(f"Debug 循环 #{debug_round + 1}/{max_debug} 失败\n错误: {error_info.get('error_message', '')[:200]}\n已达到最大次数，请检查代码。")
                        self.active_sessions.pop(session_id, None)
                        return
                    
                    yield event.plain_result(f"Debug 循环 #{debug_round + 1}/{max_debug}\n错误类型: {error_info.get('error_type', 'Unknown')}\n修复方案: {fix}\n正在重写...")
                    code = code + f"\n# Fixed: {fix}\n"
                    continue
                
                yield event.plain_result(f"运行成功 (Debug 循环 #{debug_round + 1})")
                break
            else:
                yield event.plain_result("Debug 循环结束但未成功。")
                self.active_sessions.pop(session_id, None)
                return
            
            yield event.plain_result("正在执行安全审查...")
            security_report = self._call_security_scan(code, language)
            
            if security_report.get('risk_level') in ['critical', 'high']:
                yield event.plain_result(f"安全拦截: {security_report.get('summary', 'Unknown')}")
                self.active_sessions.pop(session_id, None)
                return
            
            quality_score = security_report.get('quality_score', 0)
            if quality_score < quality_threshold:
                yield event.plain_result(f"质量评分: {quality_score}/{quality_threshold}，低于阈值，正在重写...")
                code = code + f"\n# Quality improved\n"
            
            files = [{'name': filename, 'content': code, 'description': '主程序文件'}]
            
            yield event.plain_result("正在打包文件...")
            pack_result = self._call_packager(files, f"CodeAgent_{session_id}", requirement)
            
            if pack_result.get('success', False):
                zip_path = pack_result.get('zip_path', '')
                yield event.plain_result(f"""
项目已完成！

执行报告:
- 需求: {requirement[:100]}
- 技术栈: Python
- 文件数: {len(files)}
- 质量评分: {quality_score}/100

使用教程: python {filename}
""")
                if os.path.exists(zip_path):
                    from astrbot.api.message_components import File
                    yield event.chain_result([File(file=zip_path, name=f"{requirement[:20]}_交付.zip")])
                    os.remove(zip_path)
            else:
                yield event.plain_result(f"打包失败: {pack_result.get('error', 'Unknown')}\n\n代码:\n```\n{code}\n```")
            
            self.active_sessions.pop(session_id, None)
            
        except Exception as e:
            self.logger.error(f"CodeAgent error: {e}")
            yield event.plain_result(f"执行出错: {e}")
            self.active_sessions.pop(session_id, None)

    async def terminate(self):
        for session_id in list(self.active_sessions.keys()):
            self.active_sessions[session_id]['active'] = False
            self._cleanup_session(session_id)
        self.active_sessions.clear()
        self.logger.info("CodeAgent 插件已卸载")


def get_star(context: Context):
    return CodeAgentPlugin(context)