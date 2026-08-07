#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeAgent 沙箱执行环境
功能：在隔离环境中执行代码，限制 CPU、内存、网络、文件系统、运行时间
作者: Evo
日期: 2026-08-07
路径：./scripts/codeagent_sandbox.py
"""

import os
import sys
import json
import resource
import signal
import subprocess
import time
import shutil
import tempfile
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, field

@dataclass
class SandboxConfig:
    cpu_time_limit: int = 60
    wall_time_limit: int = 120
    memory_limit_mb: int = 512
    file_size_limit_mb: int = 10
    total_size_limit_mb: int = 50
    allow_network: bool = False
    network_whitelist: List[str] = field(default_factory=lambda: [
        'pypi.org', 'files.pythonhosted.org', 'cdn.jsdelivr.net',
        'github.com', 'raw.githubusercontent.com', 'registry.npmjs.org', 'unpkg.com'
    ])
    workspace_root: str = "./codeagent_workspace"
    allow_write: bool = True
    allow_read: bool = True
    allow_delete: bool = False
    timeout_signal: int = signal.SIGTERM
    encoding: str = 'utf-8'
    max_files: int = 50
    max_subprocesses: int = 5

class ResourceLimiter:
    def __init__(self, config: SandboxConfig):
        self.config = config
    
    def apply_limits(self):
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (self.config.cpu_time_limit, self.config.cpu_time_limit + 1))
            mem = self.config.memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_DATA, (mem, mem))
            resource.setrlimit(resource.RLIMIT_STACK, (mem // 4, mem // 4))
            file_limit = self.config.file_size_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
            resource.setrlimit(resource.RLIMIT_NPROC, (self.config.max_subprocesses, self.config.max_subprocesses))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        except Exception:
            pass

class TimeoutManager:
    def __init__(self, timeout_seconds: int):
        self.timeout = timeout_seconds
        self._timed_out = False
        self._old_handler = None
    
    def __enter__(self):
        def _handler(signum, frame):
            self._timed_out = True
            raise TimeoutError(f"执行超时（{self.timeout}秒）")
        self._old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(self.timeout)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.alarm(0)
        if self._old_handler:
            signal.signal(signal.SIGALRM, self._old_handler)
        return False

class SandboxExecutor:
    DANGEROUS_PATTERNS = [
        (r'os\.remove\s*\(', '文件删除'),
        (r'shutil\.rmtree\s*\(', '递归删除'),
        (r'os\.unlink\s*\(', '文件删除'),
        (r'subprocess\.(call|Popen|run|check_output)\s*\(', '子进程调用'),
        (r'os\.system\s*\(', '系统命令执行'),
        (r'eval\s*\(', 'eval执行'),
        (r'exec\s*\(', 'exec执行'),
        (r'__import__\s*\(', '动态导入'),
        (r'compile\s*\(', '代码编译'),
        (r'rm\s+-rf\s*/', '危险shell'),
        (r'dd\s+if=', '危险shell'),
        (r'mkfs\s+', '危险shell'),
        (r':\(\)\{\s*:\|:&\s*\};:', 'fork炸弹'),
        (r'base64\.b64decode\s*\(', 'base64解码'),
        (r'ctypes\.(CDLL|windll|LibraryLoader)', 'ctypes调用'),
        (r'open\s*\(\s*[\'"]/etc/', '敏感文件'),
        (r'open\s*\(\s*[\'"]/root/', '敏感文件'),
        (r'open\s*\(\s*[\'"]/sys/', '敏感文件'),
        (r'open\s*\(\s*[\'"]/proc/', '敏感文件'),
        (r'socket\.(socket|create_connection|connect)', '网络操作'),
    ]
    
    def __init__(self, config: SandboxConfig = None):
        self.config = config or SandboxConfig()
        self.workspace = Path(self.config.workspace_root).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._temp_dirs = []
    
    def _get_session_workspace(self, session_id: str) -> Path:
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)
        session_dir = self.workspace / safe_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
    
    def _build_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        env['TMPDIR'] = str(self.workspace / 'tmp')
        env['TEMP'] = env['TMPDIR']
        env['TMP'] = env['TMPDIR']
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTHONHASHSEED'] = 'random'
        env['PYTHONNOUSERSITE'] = '1'
        if not self.config.allow_network:
            env['http_proxy'] = ''
            env['https_proxy'] = ''
            env['no_proxy'] = '*'
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        return env
    
    def _check_security(self, code: str) -> Tuple[bool, str, Optional[int]]:
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pattern, msg in self.DANGEROUS_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    return False, f"{msg} (行 {i})", i
        return True, "通过", None
    
    def _check_file_operation(self, path: str) -> Tuple[bool, str]:
        if not self.config.allow_write and ('w' in path or 'write' in path):
            return False, "写入被禁止"
        if not self.config.allow_delete and any(k in path for k in ['rm', 'del', 'remove']):
            return False, "删除被禁止"
        return True, "允许"
    
    def execute(self, code: str, session_id: str, language: str = 'python',
                filename: str = 'main.py', args: list = None) -> Dict[str, Any]:
        result = {
            'success': False, 'stdout': '', 'stderr': '', 'exit_code': -1,
            'time_elapsed': 0, 'files': [], 'error': None, 'security_warning': None,
            'resource_usage': {}
        }
        
        safe, warning, line = self._check_security(code)
        if not safe:
            result['security_warning'] = warning
            result['error'] = f"安全拦截: {warning}"
            return result
        
        session_dir = self._get_session_workspace(session_id)
        file_path = session_dir / filename
        
        try:
            file_path.write_text(code, encoding=self.config.encoding)
        except Exception as e:
            result['error'] = f"写入文件失败: {e}"
            return result
        
        if language == 'python':
            cmd = ['python3', '-u', str(file_path)] + (args or [])
        elif language == 'javascript':
            cmd = ['node', str(file_path)] + (args or [])
        elif language == 'bash':
            os.chmod(file_path, 0o755)
            cmd = ['bash', str(file_path)] + (args or [])
        else:
            result['error'] = f"不支持的语言: {language}"
            return result
        
        env = self._build_env()
        start_time = time.time()
        
        try:
            limiter = ResourceLimiter(self.config)
            limiter.apply_limits()
            
            with TimeoutManager(self.config.wall_time_limit):
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(session_dir),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding=self.config.encoding,
                    preexec_fn=os.setsid if hasattr(os, 'setsid') else None
                )
                
                try:
                    stdout, stderr = proc.communicate(timeout=self.config.wall_time_limit)
                    result['stdout'] = stdout[:100000] if len(stdout) > 100000 else stdout
                    result['stderr'] = stderr[:50000] if len(stderr) > 50000 else stderr
                    if len(stdout) > 100000:
                        result['stdout'] += f"\n... (输出截断，共 {len(stdout)} 字符)"
                    result['exit_code'] = proc.returncode
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except:
                        proc.kill()
                    proc.wait(timeout=2)
                    result['error'] = f"执行超时（{self.config.wall_time_limit}秒）"
                    return result
                
        except TimeoutError as e:
            result['error'] = str(e)
            return result
        except Exception as e:
            result['error'] = f"执行异常: {e}"
            return result
        
        try:
            result['files'] = []
            total_size = 0
            for item in session_dir.iterdir():
                if item.is_file() and item.name != filename and not item.name.startswith('.'):
                    size = item.stat().st_size
                    if size > self.config.file_size_limit_mb * 1024 * 1024:
                        continue
                    total_size += size
                    result['files'].append({
                        'name': item.name,
                        'size': size,
                        'path': str(item.relative_to(self.workspace))
                    })
                    if len(result['files']) > self.config.max_files:
                        break
            if total_size > self.config.total_size_limit_mb * 1024 * 1024:
                result['warning'] = f"项目总大小超出限制 ({total_size} bytes)"
        except Exception as e:
            result['warning'] = f"文件收集失败: {e}"
        
        result['time_elapsed'] = time.time() - start_time
        result['success'] = (result['exit_code'] == 0 and result['error'] is None)
        
        return result

def main():
    import argparse
    parser = argparse.ArgumentParser(description='CodeAgent 沙箱执行环境')
    parser.add_argument('--code', type=str, help='代码内容')
    parser.add_argument('--code-file', type=str, help='代码文件路径')
    parser.add_argument('--session-id', type=str, default='test', help='会话ID')
    parser.add_argument('--language', type=str, default='python', help='编程语言')
    parser.add_argument('--filename', type=str, default='main.py', help='文件名')
    parser.add_argument('--args', type=str, nargs='*', help='命令行参数')
    parser.add_argument('--config', type=str, help='配置文件路径')
    parser.add_argument('--test', action='store_true', help='运行测试')
    
    args = parser.parse_args()
    
    if args.test:
        print("🧪 运行沙箱测试...")
        config = SandboxConfig()
        executor = SandboxExecutor(config)
        
        test_code = '''
import os
print("Hello from sandbox!")
print(f"当前目录: {os.getcwd()}")
with open("test_output.txt", "w") as f:
    f.write("Test file created\\n")
print("测试完成")
'''
        result = executor.execute(
            code=test_code,
            session_id='test_session',
            language='python',
            filename='test.py'
        )
        
        print(f"成功: {result['success']}")
        print(f"stdout:\n{result['stdout']}")
        if result['files']:
            print(f"生成的文件: {[f['name'] for f in result['files']]}")
        if result['error']:
            print(f"错误: {result['error']}")
        print("✅ 测试完成")
        return
    
    if args.code:
        code = args.code
    elif args.code_file:
        with open(args.code_file, 'r', encoding='utf-8') as f:
            code = f.read()
    else:
        print("错误: 请提供 --code 或 --code-file", file=sys.stderr)
        sys.exit(1)
    
    config = SandboxConfig()
    if args.config:
        with open(args.config, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
    
    executor = SandboxExecutor(config)
    result = executor.execute(
        code=code,
        session_id=args.session_id,
        language=args.language,
        filename=args.filename,
        args=args.args
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

if __name__ == '__main__':
    main()