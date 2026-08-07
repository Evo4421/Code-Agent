#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeAgent 安全审查模块
功能：深度检测代码中的恶意模式、后门、漏洞和敏感操作以及代码质量评估
作者: Evo
日期: 2026-08-07
路径：./scripts/codeagent_security.py
"""

import os
import re
import sys
import json
import ast
import base64
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

class RiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class SecurityFinding:
    level: RiskLevel
    category: str
    message: str
    line: int
    code_snippet: str
    suggestion: str = ""
    file_path: str = ""

@dataclass
class SecurityReport:
    file_path: str
    findings: List[SecurityFinding] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.SAFE
    summary: str = ""
    passed: bool = True
    quality_score: int = 0
    quality_details: Dict[str, Any] = field(default_factory=dict)
    
    def add_finding(self, finding: SecurityFinding):
        self.findings.append(finding)
        if finding.level == RiskLevel.CRITICAL:
            self.risk_level = RiskLevel.CRITICAL
            self.passed = False
        elif finding.level == RiskLevel.HIGH and self.risk_level.value != "critical":
            self.risk_level = RiskLevel.HIGH
            self.passed = False
        elif finding.level == RiskLevel.MEDIUM and self.risk_level.value not in ["critical", "high"]:
            self.risk_level = RiskLevel.MEDIUM
        elif finding.level == RiskLevel.LOW and self.risk_level.value not in ["critical", "high", "medium"]:
            self.risk_level = RiskLevel.LOW

class PythonCodeQualityChecker:
    
    def __init__(self):
        self.score = 100
        self.details = {}
        self.issues = []
    
    def check(self, code: str) -> Tuple[int, Dict[str, Any], List[str]]:
        self.score = 100
        self.details = {}
        self.issues = []
        
        lines = code.split('\n')
        total_lines = len([l for l in lines if l.strip()])
        
        self._check_docstrings(code, total_lines)
        self._check_complexity(lines)
        self._check_naming(lines)
        self._check_line_length(lines)
        self._check_imports(code)
        self._check_comments(lines, total_lines)
        self._check_functions(code)
        self._check_error_handling(code)
        self._check_type_hints(code)
        self._check_code_smells(code)
        
        self.score = max(0, min(100, self.score))
        return self.score, self.details, self.issues
    
    def _check_docstrings(self, code: str, total_lines: int):
        docstring_pattern = r'""".*?"""|\'\'\'.*?\'\'\''
        docstrings = re.findall(docstring_pattern, code, re.DOTALL)
        if total_lines > 20 and len(docstrings) < 2:
            self.score -= 10
            self.issues.append("代码缺少文档字符串，建议添加函数/类说明")
        self.details['docstrings'] = len(docstrings)
    
    def _check_complexity(self, lines: List[str]):
        nesting = 0
        max_nesting = 0
        for line in lines:
            stripped = line.strip()
            if stripped.endswith(':') and not stripped.startswith('#'):
                nesting += 1
                max_nesting = max(max_nesting, nesting)
            elif stripped.startswith('return') or stripped.startswith('break') or stripped.startswith('continue'):
                nesting = max(0, nesting - 1)
        if max_nesting > 4:
            self.score -= 15
            self.issues.append(f"最大嵌套深度 {max_nesting}，建议不超过4层")
        if max_nesting > 6:
            self.score -= 10
            self.issues.append("嵌套深度过高，建议拆分函数")
        self.details['max_nesting'] = max_nesting
    
    def _check_naming(self, lines: List[str]):
        bad_names = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(('def ', 'class ')):
                import re
                match = re.search(r'(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', stripped)
                if match:
                    name = match.group(1)
                    if len(name) == 1 and name not in ['i', 'j', 'k', 'x', 'y', 'z']:
                        bad_names.append(name)
                    if name.isupper():
                        pass
        if bad_names:
            self.score -= min(10, len(bad_names) * 2)
            self.issues.append(f"不规范的命名: {', '.join(bad_names[:5])}")
        self.details['naming_issues'] = len(bad_names)
    
    def _check_line_length(self, lines: List[str]):
        long_lines = [i+1 for i, l in enumerate(lines) if len(l) > 120]
        if long_lines:
            self.score -= min(10, len(long_lines) * 1)
            self.issues.append(f"有 {len(long_lines)} 行超过120字符 (行号: {', '.join(map(str, long_lines[:3]))})")
        self.details['long_lines'] = len(long_lines)
    
    def _check_imports(self, code: str):
        lines = code.split('\n')
        imports = [l for l in lines if l.strip().startswith(('import ', 'from ')) and not l.strip().startswith('#')]
        wildcard_imports = [l for l in imports if ' import *' in l]
        if wildcard_imports:
            self.score -= 10
            self.issues.append("使用了通配符导入 (import *)，建议显式导入")
        self.details['imports'] = len(imports)
        self.details['wildcard_imports'] = len(wildcard_imports)
    
    def _check_comments(self, lines: List[str], total_lines: int):
        comment_lines = [l for l in lines if l.strip().startswith('#')]
        ratio = len(comment_lines) / max(1, total_lines)
        if total_lines > 30 and ratio < 0.05:
            self.score -= 10
            self.issues.append("注释过少 (<5%)，建议增加注释说明")
        if ratio > 0.4:
            self.score -= 5
            self.issues.append("注释过多 (>40%)，可能是代码可读性不足")
        self.details['comment_ratio'] = round(ratio * 100, 1)
    
    def _check_functions(self, code: str):
        import re
        func_pattern = r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)'
        funcs = re.findall(func_pattern, code)
        long_funcs = 0
        for func in funcs:
            pattern = rf'def\s+{func}\s*\([^)]*\):[^\n]*\n((?:\s+.*\n)*?)(?=\n\S|$)'
            match = re.search(pattern, code, re.MULTILINE)
            if match:
                body = match.group(1)
                body_lines = [l for l in body.split('\n') if l.strip()]
                if len(body_lines) > 50:
                    long_funcs += 1
        if long_funcs:
            self.score -= min(15, long_funcs * 5)
            self.issues.append(f"有 {long_funcs} 个函数超过50行，建议拆分")
        self.details['function_count'] = len(funcs)
        self.details['long_functions'] = long_funcs
    
    def _check_error_handling(self, code: str):
        import re
        try_pattern = r'try\s*:'
        except_pattern = r'except\s*:'
        except_with_type = r'except\s+[a-zA-Z]'
        try_count = len(re.findall(try_pattern, code))
        except_count = len(re.findall(except_pattern, code))
        except_type_count = len(re.findall(except_with_type, code))
        if except_count > except_type_count:
            self.score -= 10
            self.issues.append("存在裸露的 except，建议指定异常类型")
        self.details['try_count'] = try_count
        self.details['except_typed'] = except_type_count
    
    def _check_type_hints(self, code: str):
        import re
        type_hint_pattern = r'[a-zA-Z_][a-zA-Z0-9_]*\s*:\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[=,]|->\s*[a-zA-Z_]'
        hints = len(re.findall(type_hint_pattern, code))
        functions = len(re.findall(r'def\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(', code))
        if functions > 5 and hints < functions * 0.5:
            self.score -= 10
            self.issues.append("函数缺少类型注解，建议添加")
        self.details['type_hints'] = hints
    
    def _check_code_smells(self, code: str):
        smells = 0
        if 'global ' in code:
            smells += 1
            self.issues.append("使用了 global，建议避免使用全局变量")
        if re.search(r'except\s*:\s*pass', code):
            smells += 1
            self.issues.append("存在空的 except: pass，可能隐藏重要错误")
        if re.search(r'if\s+len\([^)]*\)\s*[=!]=\s*0', code):
            smells += 1
            self.issues.append("使用 len(x) != 0 判断空，建议使用 'if x:'")
        if re.search(r'type\([^)]*\)\s*==', code):
            smells += 1
            self.issues.append("使用 type(x) == 判断类型，建议使用 isinstance")
        self.details['code_smells'] = smells
        if smells > 0:
            self.score -= min(10, smells * 3)

class PythonSecurityChecker(ast.NodeVisitor):
    
    def __init__(self, file_path: str = ""):
        self.file_path = file_path
        self.findings: List[SecurityFinding] = []
        self.imported_modules: Set[str] = set()
        self._current_line = 0
        self._current_code = ""
        
        self.DANGEROUS_MODULES = {
            'os': RiskLevel.HIGH, 'subprocess': RiskLevel.HIGH, 'shutil': RiskLevel.MEDIUM,
            'sys': RiskLevel.LOW, 'socket': RiskLevel.HIGH, 'pickle': RiskLevel.MEDIUM,
            'marshal': RiskLevel.MEDIUM, 'ctypes': RiskLevel.CRITICAL, 'cffi': RiskLevel.CRITICAL,
            'distutils': RiskLevel.MEDIUM, 'tempfile': RiskLevel.LOW, 'pathlib': RiskLevel.LOW,
            'base64': RiskLevel.MEDIUM, 'codecs': RiskLevel.MEDIUM, 'importlib': RiskLevel.MEDIUM,
            'builtins': RiskLevel.HIGH, 'pty': RiskLevel.HIGH, 'fcntl': RiskLevel.MEDIUM,
            'mmap': RiskLevel.MEDIUM, 'resource': RiskLevel.MEDIUM,
        }
        
        self.DANGEROUS_CALLS = {
            'os.system': RiskLevel.HIGH, 'os.popen': RiskLevel.HIGH, 'os.popen2': RiskLevel.HIGH,
            'os.popen3': RiskLevel.HIGH, 'os.popen4': RiskLevel.HIGH, 'os.spawnl': RiskLevel.HIGH,
            'os.spawnle': RiskLevel.HIGH, 'os.spawnlp': RiskLevel.HIGH, 'os.spawnlpe': RiskLevel.HIGH,
            'os.spawnv': RiskLevel.HIGH, 'os.spawnve': RiskLevel.HIGH, 'os.spawnvp': RiskLevel.HIGH,
            'os.spawnvpe': RiskLevel.HIGH, 'os.kill': RiskLevel.HIGH, 'os.remove': RiskLevel.HIGH,
            'os.unlink': RiskLevel.HIGH, 'os.rmdir': RiskLevel.HIGH, 'os.removedirs': RiskLevel.HIGH,
            'os.rename': RiskLevel.LOW, 'os.chmod': RiskLevel.MEDIUM, 'os.chown': RiskLevel.MEDIUM,
            'os.setuid': RiskLevel.CRITICAL, 'os.setgid': RiskLevel.CRITICAL, 'os.seteuid': RiskLevel.CRITICAL,
            'os.setegid': RiskLevel.CRITICAL, 'os.execv': RiskLevel.CRITICAL, 'os.execve': RiskLevel.CRITICAL,
            'os.execl': RiskLevel.CRITICAL, 'os.execlp': RiskLevel.CRITICAL, 'os.execvpe': RiskLevel.CRITICAL,
            'subprocess.call': RiskLevel.HIGH, 'subprocess.check_call': RiskLevel.HIGH,
            'subprocess.check_output': RiskLevel.HIGH, 'subprocess.Popen': RiskLevel.HIGH,
            'subprocess.run': RiskLevel.HIGH, 'shutil.rmtree': RiskLevel.HIGH, 'shutil.move': RiskLevel.MEDIUM,
            'shutil.copy': RiskLevel.LOW, 'shutil.copytree': RiskLevel.MEDIUM,
            'socket.connect': RiskLevel.HIGH, 'socket.connect_ex': RiskLevel.HIGH,
            'socket.socket': RiskLevel.HIGH, 'socket.create_connection': RiskLevel.HIGH,
            'pickle.load': RiskLevel.MEDIUM, 'pickle.loads': RiskLevel.MEDIUM,
            'marshal.load': RiskLevel.MEDIUM, 'marshal.loads': RiskLevel.MEDIUM,
            'ctypes.CDLL': RiskLevel.CRITICAL, 'ctypes.windll': RiskLevel.CRITICAL,
            'ctypes.get_errno': RiskLevel.MEDIUM, 'ctypes.set_errno': RiskLevel.MEDIUM,
            'eval': RiskLevel.CRITICAL, 'exec': RiskLevel.CRITICAL, 'compile': RiskLevel.HIGH,
            '__import__': RiskLevel.HIGH, 'breakpoint': RiskLevel.LOW, 'exit': RiskLevel.MEDIUM,
            'quit': RiskLevel.MEDIUM, 'globals': RiskLevel.LOW, 'locals': RiskLevel.LOW,
            'dir': RiskLevel.LOW, 'getattr': RiskLevel.LOW, 'setattr': RiskLevel.LOW,
            'delattr': RiskLevel.LOW, 'memoryview': RiskLevel.MEDIUM,
        }
        
        self.DANGEROUS_PATTERNS = [
            (r'rm\s+-rf\s+/?', RiskLevel.CRITICAL, '危险 rm -rf 命令'),
            (r'dd\s+if=', RiskLevel.CRITICAL, '危险 dd 命令'),
            (r'mkfs\s+', RiskLevel.CRITICAL, '危险 mkfs 命令'),
            (r'chmod\s+777\s+', RiskLevel.HIGH, '危险 chmod 777'),
            (r'chown\s+-R', RiskLevel.HIGH, '危险递归 chown'),
            (r':\(\)\{\s*:\|:&\s*\};:', RiskLevel.CRITICAL, 'fork 炸弹'),
            (r'shutdown\s+-h', RiskLevel.CRITICAL, '关机命令'),
            (r'reboot', RiskLevel.CRITICAL, '重启命令'),
            (r'poweroff', RiskLevel.CRITICAL, '关机命令'),
            (r'curl\s+.*\|\s+(bash|sh)', RiskLevel.CRITICAL, 'curl pipe 到 shell'),
            (r'wget\s+.*\|\s+(bash|sh)', RiskLevel.CRITICAL, 'wget pipe 到 shell'),
            (r'base64\s+-d', RiskLevel.HIGH, 'base64 解码执行'),
            (r'python3?\s+-c\s+', RiskLevel.HIGH, 'Python 一行命令执行'),
        ]
    
    def visit(self, node):
        self._current_line = getattr(node, 'lineno', 0)
        self._current_code = self._get_code_snippet(node)
        return super().visit(node)
    
    def _get_code_snippet(self, node) -> str:
        if hasattr(node, 'source_lines'):
            return node.source_lines.get(self._current_line, '').strip()
        return ''
    
    def _add_finding(self, level: RiskLevel, category: str, message: str, line: int = None, suggestion: str = ""):
        self.findings.append(SecurityFinding(
            level=level, category=category, message=message,
            line=line or self._current_line, code_snippet=self._current_code,
            suggestion=suggestion, file_path=self.file_path
        ))
    
    def visit_Import(self, node):
        for alias in node.names:
            module_name = alias.name.split('.')[0]
            if module_name in self.DANGEROUS_MODULES:
                self._add_finding(
                    level=self.DANGEROUS_MODULES[module_name],
                    category='dangerous_module',
                    message=f'导入了危险模块: {module_name}',
                    suggestion='请确认此导入是否必要，如需使用请联系管理员审核'
                )
            self.imported_modules.add(module_name)
    
    def visit_ImportFrom(self, node):
        if node.module:
            module_name = node.module.split('.')[0]
            if module_name in self.DANGEROUS_MODULES:
                self._add_finding(
                    level=self.DANGEROUS_MODULES[module_name],
                    category='dangerous_module',
                    message=f'从危险模块导入: {module_name}',
                    suggestion='请确认此导入是否必要，如需使用请联系管理员审核'
                )
            self.imported_modules.add(module_name)
        for alias in node.names:
            if alias.name == '*':
                self._add_finding(
                    level=RiskLevel.MEDIUM, category='bad_practice',
                    message=f'使用 from {node.module} import *，可能引入未预期的符号',
                    suggestion='请显式导入需要的函数，避免使用 import *'
                )
    
    def visit_Call(self, node):
        func_name = self._get_call_name(node.func)
        if not func_name:
            return
        if func_name in self.DANGEROUS_CALLS:
            self._add_finding(
                level=self.DANGEROUS_CALLS[func_name],
                category='dangerous_call',
                message=f'调用了危险函数: {func_name}',
                suggestion='此操作可能危害系统安全，建议重新设计'
            )
        if func_name in ['eval', 'exec', 'compile']:
            self._check_dynamic_execution(node)
        if func_name == 'base64.b64decode':
            self._check_base64_decode(node)
        if func_name == 'open':
            self._check_open_call(node)
        self.generic_visit(node)
    
    def _get_call_name(self, node) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            obj_name = self._get_call_name(node.value)
            if obj_name:
                return f"{obj_name}.{node.attr}"
            return node.attr
        elif isinstance(node, ast.Call):
            return self._get_call_name(node.func)
        return None
    
    def _check_dynamic_execution(self, node):
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                code = first_arg.value
                for pattern, level, msg in self.DANGEROUS_PATTERNS:
                    if re.search(pattern, code, re.IGNORECASE):
                        self._add_finding(
                            level=RiskLevel.CRITICAL,
                            category='dangerous_dynamic_code',
                            message=f'动态代码中包含危险操作: {msg}',
                            suggestion='请勿在动态执行的代码中包含系统操作'
                        )
    
    def _check_base64_decode(self, node):
        parent = getattr(node, 'parent', None)
        if parent and isinstance(parent, ast.Call):
            self._add_finding(
                level=RiskLevel.CRITICAL,
                category='dangerous_execution',
                message='检测到 base64 解码后立即调用，可能存在恶意代码执行',
                suggestion='请勿使用 base64 解码执行未知代码'
            )
    
    def _check_open_call(self, node):
        if len(node.args) >= 2:
            mode_arg = node.args[1]
            if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                mode = mode_arg.value
                if 'w' in mode or 'a' in mode:
                    if len(node.args) >= 1:
                        path_arg = node.args[0]
                        if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
                            path = path_arg.value
                            dangerous_paths = ['/etc/', '/root/', '/sys/', '/proc/', '/var/']
                            for dangerous in dangerous_paths:
                                if dangerous in path:
                                    self._add_finding(
                                        level=RiskLevel.HIGH,
                                        category='dangerous_file_write',
                                        message=f'尝试写入系统目录: {path}',
                                        suggestion='请勿修改系统文件'
                                    )
    
    def visit_Constant(self, node):
        if isinstance(node.value, str):
            for pattern, level, msg in self.DANGEROUS_PATTERNS:
                if re.search(pattern, node.value, re.IGNORECASE):
                    self._add_finding(
                        level=level, category='dangerous_string',
                        message=f'字符串中包含危险命令: {msg}',
                        suggestion='请勿在代码中包含系统破坏性命令'
                    )
        self.generic_visit(node)
    
    def visit_Try(self, node):
        for handler in node.handlers:
            if handler.type is None:
                self._add_finding(
                    level=RiskLevel.LOW, category='bad_practice',
                    message='使用裸露的 except 捕获所有异常，可能隐藏错误',
                    suggestion='建议指定捕获特定异常类型'
                )
        self.generic_visit(node)

class CodeSecurityScanner:
    
    def __init__(self):
        self.findings: List[SecurityFinding] = []
    
    def scan_python(self, code: str, file_path: str = "") -> SecurityReport:
        report = SecurityReport(file_path=file_path)
        try:
            tree = ast.parse(code)
            checker = PythonSecurityChecker(file_path)
            checker.visit(tree)
            for finding in checker.findings:
                report.add_finding(finding)
        except SyntaxError as e:
            report.add_finding(SecurityFinding(
                level=RiskLevel.MEDIUM, category='syntax_error',
                message=f'语法错误: {e.msg}', line=e.lineno or 0,
                code_snippet=code.split('\n')[e.lineno - 1] if e.lineno else '',
                suggestion='请检查代码语法'
            ))
            report.passed = False
            report.risk_level = RiskLevel.MEDIUM
        
        quality_checker = PythonCodeQualityChecker()
        quality_score, quality_details, quality_issues = quality_checker.check(code)
        report.quality_score = quality_score
        report.quality_details = quality_details
        
        for issue in quality_issues:
            report.add_finding(SecurityFinding(
                level=RiskLevel.LOW, category='quality_issue',
                message=issue, line=0, code_snippet='',
                suggestion='建议改进代码质量'
            ))
        
        if report.findings:
            critical = sum(1 for f in report.findings if f.level == RiskLevel.CRITICAL)
            high = sum(1 for f in report.findings if f.level == RiskLevel.HIGH)
            medium = sum(1 for f in report.findings if f.level == RiskLevel.MEDIUM)
            low = sum(1 for f in report.findings if f.level == RiskLevel.LOW)
            report.summary = f"发现 {len(report.findings)} 个问题: "
            if critical:
                report.summary += f"{critical} 个严重, "
            if high:
                report.summary += f"{high} 个高危, "
            if medium:
                report.summary += f"{medium} 个中危, "
            if low:
                report.summary += f"{low} 个低危"
        
        return report
    
    def scan_shell(self, code: str, file_path: str = "") -> SecurityReport:
        report = SecurityReport(file_path=file_path)
        patterns = [
            (r'rm\s+-rf\s+/?', RiskLevel.CRITICAL, '危险: rm -rf /'),
            (r'dd\s+if=', RiskLevel.CRITICAL, '危险: dd 命令'),
            (r'mkfs\s+', RiskLevel.CRITICAL, '危险: mkfs 命令'),
            (r'chmod\s+777\s+', RiskLevel.HIGH, '危险: chmod 777'),
            (r'chown\s+-R', RiskLevel.HIGH, '危险: chown -R'),
            (r':\(\)\{\s*:\|:&\s*\};:', RiskLevel.CRITICAL, 'fork 炸弹'),
            (r'shutdown\s+-h', RiskLevel.CRITICAL, '关机命令'),
            (r'reboot', RiskLevel.CRITICAL, '重启命令'),
            (r'poweroff', RiskLevel.CRITICAL, '关机命令'),
            (r'curl\s+.*\|\s+(bash|sh)', RiskLevel.CRITICAL, 'curl pipe 到 shell'),
            (r'wget\s+.*\|\s+(bash|sh)', RiskLevel.CRITICAL, 'wget pipe 到 shell'),
            (r'>\s*/dev/sd', RiskLevel.CRITICAL, '写入块设备'),
            (r'>\s*/etc/passwd', RiskLevel.CRITICAL, '写入 passwd'),
            (r'>\s*/etc/shadow', RiskLevel.CRITICAL, '写入 shadow'),
            (r'kill\s+-9\s+', RiskLevel.HIGH, '强制杀进程'),
        ]
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            for pattern, level, msg in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    report.add_finding(SecurityFinding(
                        level=level, category='dangerous_command',
                        message=msg, line=i, code_snippet=line.strip(),
                        suggestion='请移除危险命令或修改实现方式'
                    ))
        if report.findings:
            report.summary = f"发现 {len(report.findings)} 个危险命令"
        report.quality_score = 80
        report.quality_details = {'shell_check': 'basic'}
        return report
    
    def scan_javascript(self, code: str, file_path: str = "") -> SecurityReport:
        report = SecurityReport(file_path=file_path)
        patterns = [
            (r'eval\s*\(', RiskLevel.CRITICAL, '危险: eval 执行'),
            (r'Function\s*\(', RiskLevel.HIGH, '危险: Function 构造函数'),
            (r'setTimeout\s*\(.+,\s*\d+\)', RiskLevel.MEDIUM, '延迟代码执行'),
            (r'setInterval\s*\(.+,\s*\d+\)', RiskLevel.MEDIUM, '定时代码执行'),
            (r'document\.write\s*\(', RiskLevel.MEDIUM, '动态写入 DOM'),
            (r'innerHTML\s*=', RiskLevel.MEDIUM, '直接修改 HTML'),
            (r'exec\s*\(', RiskLevel.CRITICAL, '危险: exec 执行'),
            (r'require\s*\(\s*[\'"]child_process', RiskLevel.HIGH, '引入 child_process'),
            (r'require\s*\(\s*[\'"]fs', RiskLevel.HIGH, '引入 fs'),
            (r'fs\.writeFile', RiskLevel.HIGH, '写入文件'),
            (r'fs\.unlink', RiskLevel.HIGH, '删除文件'),
            (r'fs\.rmdir', RiskLevel.HIGH, '删除目录'),
            (r'child_process\.exec', RiskLevel.HIGH, '执行系统命令'),
            (r'child_process\.spawn', RiskLevel.HIGH, '执行系统命令'),
            (r'process\.exit', RiskLevel.MEDIUM, '进程退出'),
            (r'process\.kill', RiskLevel.HIGH, '杀进程'),
        ]
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            for pattern, level, msg in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    report.add_finding(SecurityFinding(
                        level=level, category='dangerous_command',
                        message=msg, line=i, code_snippet=line.strip(),
                        suggestion='请移除危险操作或修改实现方式'
                    ))
        if report.findings:
            report.summary = f"发现 {len(report.findings)} 个危险操作"
        report.quality_score = 80
        report.quality_details = {'js_check': 'basic'}
        return report

def scan_code(code: str, file_path: str = "", language: str = "auto") -> SecurityReport:
    scanner = CodeSecurityScanner()
    if language == "auto":
        if file_path:
            ext = Path(file_path).suffix.lower()
            if ext in ['.py', '.pyw']:
                language = 'python'
            elif ext in ['.sh', '.bash', '.zsh']:
                language = 'shell'
            elif ext in ['.js', '.mjs']:
                language = 'javascript'
            else:
                language = 'python'
        else:
            language = 'python'
    
    if language == 'python':
        return scanner.scan_python(code, file_path)
    elif language == 'shell':
        return scanner.scan_shell(code, file_path)
    elif language == 'javascript':
        return scanner.scan_javascript(code, file_path)
    else:
        report = SecurityReport(file_path=file_path)
        report.add_finding(SecurityFinding(
            level=RiskLevel.LOW, category='unsupported',
            message=f'不支持的语言: {language}，仅进行基础扫描',
            line=0, code_snippet='', suggestion='请确保代码语言正确'
        ))
        return report

def main():
    import argparse
    parser = argparse.ArgumentParser(description='CodeAgent 安全审查模块')
    parser.add_argument('--code', type=str, help='代码内容')
    parser.add_argument('--code-file', type=str, help='代码文件路径')
    parser.add_argument('--language', type=str, default='auto', help='编程语言')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--test', action='store_true', help='运行测试')
    
    args = parser.parse_args()
    
    if args.test:
        print("🧪 运行安全审查测试...")
        test_python = '''
import os
import subprocess
import base64

def dangerous_function():
    os.system('rm -rf /tmp')
    subprocess.call(['shutdown', '-h', 'now'])
    code = base64.b64decode('cHJpbnQoImhhY2tlZCIp')
    eval(code)

def safe_function():
    print("Hello, world!")
'''
        report = scan_code(test_python, 'test.py', 'python')
        print(f"报告: {report.file_path}")
        print(f"风险等级: {report.risk_level.value}")
        print(f"通过: {report.passed}")
        print(f"摘要: {report.summary}")
        print(f"质量评分: {report.quality_score}/100")
        for finding in report.findings:
            print(f"  [{finding.level.value}] {finding.message} (行 {finding.line})")
        print("✅ 测试完成")
        return
    
    if args.code:
        code = args.code
    elif args.code_file:
        with open(args.code_file, 'r', encoding='utf-8', errors='ignore') as f:
            code = f.read()
    else:
        print("错误: 请提供 --code 或 --code-file", file=sys.stderr)
        sys.exit(1)
    
    report = scan_code(code, args.code_file or '', args.language)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2, default=str)
    else:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str))
    
    if report.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH] or report.quality_score < 75:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()